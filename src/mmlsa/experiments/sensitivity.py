"""Stage 2, reproducibility and sensitivity (milestone M11, success metric 1).

Two questions, ``docs/EXPERIMENTS.md`` Stage 2:

* **(a) Run-to-run stability.** At the reference chunk length (``chunking.P``), the ``M`` runs of
  one pipeline run are compared with each other. Per creation: its ``M`` scores, their mean,
  standard deviation and coefficient of variation, and its label in each run, where run ``r`` is
  thresholded on its own scores by the configured method. Per chunk: the CV of its delta across the
  runs, which is what the book's rule "raise ``M`` if the CV is large on a non-trivial fraction of
  chunks" is about.
* **(b) Chunk-length sensitivity.** One full pipeline run per ``P`` in
  ``experiment.sensitivity.P_values``; each creation's final label at each ``P``.

**Passes if** no creation changes label, across the runs in (a) or across ``P`` in (b), except a
creation that is borderline somewhere or on the exempt list (``experiment.sensitivity.exempt``, the
spec's named borderline set, kept in config by R1).

**The M recommendation.** For each ``m`` in ``experiment.sensitivity.M_values``, the creations are
re-scored from their first ``m`` runs and re-thresholded; the smallest ``m`` whose labels agree with
those of all ``M`` runs is recommended, unless the share of unstable chunks says to raise ``M``.

The sweep is a set of ordinary runs, ``<sweep id>-P<P>``, each immutable and resumable like any run,
plus one directory ``<sweep id>`` holding the tables and the verdict. Every ``P`` changes the chunks,
so no ``P`` reuses another's answers: the plan prints the cost before anything is sent.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from mmlsa.config import Config
from mmlsa.experiments.validation import coefficient_of_variation
from mmlsa.pipeline.classify import AUTHENTIC, SUSPICIOUS, compute_threshold
from mmlsa.pipeline.orchestrator import (
    DryRunPlan,
    _code_version,
    _dump,
    build_run_id,
    execute_run,
    is_complete,
    plan_run,
)
from mmlsa.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)

PASS, FAIL, UNDEFINED = "pass", "fail", "undefined"


class SensitivityError(Exception):
    """Raised when the sweep cannot be set up or its runs cannot be read."""


# ------------------------------------------------------------------------------------ the members


def member_config(config: Config, chunk_size: int) -> Config:
    """The sweep's configuration with ``chunking.P`` set to one value of the sweep."""
    data = config.to_dict()
    data["chunking"]["P"] = chunk_size
    return Config.model_validate(data).bind_root(config.root)


def member_run_id(sweep_id: str, chunk_size: int) -> str:
    """The run id of the sweep's run at one ``P``."""
    return f"{sweep_id}-P{chunk_size}"


def _sweep_values(config: Config) -> list[int]:
    """The ``P`` values, with the reference ``P`` among them."""
    values = sorted(set(config.experiment.sensitivity.P_values))
    if config.chunking.P not in values:
        raise SensitivityError(
            f"the reference chunking.P = {config.chunking.P} is not among "
            f"experiment.sensitivity.P_values {values}; question (a) is measured at it"
        )
    too_many = [m for m in config.experiment.sensitivity.M_values if m > config.run.M]
    if too_many:
        raise SensitivityError(
            f"M_values {too_many} exceed run.M = {config.run.M}: an M is read from the first M "
            "runs, so run.M must be the largest"
        )
    return values


@dataclass(frozen=True)
class SweepPlan:
    """What the sweep would send, before anything is sent."""

    sweep_id: str
    members: list[tuple[int, DryRunPlan]]

    @property
    def total_calls(self) -> int:
        """Every call over all ``P`` values, retries aside."""
        return sum(plan.total_calls for _, plan in self.members)

    @property
    def calls_to_issue(self) -> int:
        """The calls the cache does not already answer."""
        return sum(plan.calls_to_issue for _, plan in self.members)


def plan_sweep(config: Config, sweep_id: str) -> SweepPlan:
    """Plan one run per ``P`` without touching a provider."""
    return SweepPlan(
        sweep_id=sweep_id,
        members=[
            (size, plan_run(member_config(config, size), run_id=member_run_id(sweep_id, size)))
            for size in _sweep_values(config)
        ],
    )


# ---------------------------------------------------------------------------- reading the runs


@dataclass
class MemberScores:
    """What the analysis needs from one finished run of the sweep."""

    P: int
    run_id: str
    tau: float
    per_run: dict[str, list[float | None]]
    score: dict[str, float | None]
    label: dict[str, str]
    borderline: set[str]
    chunk_deltas: dict[tuple[str, int], list[float | None]] = field(default_factory=dict)


def _number(text: str | None) -> float | None:
    return float(text) if text not in (None, "") else None


def read_member(run_dir: Path, chunk_size: int, runs: int) -> MemberScores:
    """Read a finished run's per-run scores, labels and per-chunk deltas."""
    if not is_complete(run_dir):
        raise SensitivityError(f"{run_dir} is not a finished run")
    per_run: dict[str, list[float | None]] = {}
    score: dict[str, float | None] = {}
    label: dict[str, str] = {}
    borderline: set[str] = set()
    with (run_dir / "scores.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = row["creation_id"]
            per_run[name] = [_number(row.get(f"s_{r}")) for r in range(1, runs + 1)]
            score[name] = _number(row["score_mean"])
            label[name] = row["label"]
            if row.get("borderline", "").strip().lower() in {"true", "1"}:
                borderline.add(name)

    chunk_deltas: dict[tuple[str, int], list[float | None]] = {}
    for r in range(1, runs + 1):
        with (run_dir / "deltas" / f"run_{r}.csv").open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["creation_id"] not in per_run:
                    continue  # the injected noise text is scored as a diagnostic, never judged
                key = (row["creation_id"], int(row["chunk_index"]))
                chunk_deltas.setdefault(key, [None] * runs)[r - 1] = _number(row["delta"])

    threshold = json.loads((run_dir / "threshold.json").read_text(encoding="utf-8"))
    return MemberScores(
        P=chunk_size,
        run_id=run_dir.name,
        tau=float(threshold["tau"]),
        per_run=per_run,
        score=score,
        label=label,
        borderline=borderline,
        chunk_deltas=chunk_deltas,
    )


# -------------------------------------------------------------------------------- the analysis


def threshold_labels(
    scores: dict[str, float | None], config: Config
) -> tuple[float | None, dict[str, str], set[str]]:
    """Step 6 on one set of scores: ``tau``, each creation's label, and the borderline set."""
    scored = {name: value for name, value in scores.items() if value is not None}
    if len(scored) < 2:
        return None, dict.fromkeys(scores, "unscored"), set()
    classify = config.classify
    tau = compute_threshold(
        list(scored.values()),
        method=classify.method,
        cross_check_skimage=False,
        min_separability=classify.bimodality_min_separability,
        min_gap_ratio=classify.bimodality_min_gap_ratio,
        manual_tau=classify.manual_tau,
        seed=config.run.seed,
    ).tau
    labels = {
        name: "unscored" if value is None else (SUSPICIOUS if value > tau else AUTHENTIC)
        for name, value in scores.items()
    }
    near = {name for name, value in scored.items() if abs(value - tau) <= classify.borderline_band}
    return tau, labels, near


def stability_rows(
    member: MemberScores, config: Config, exempt: set[str]
) -> tuple[list[dict[str, Any]], list[float | None]]:
    """Question (a): one row per creation, and each run's own ``tau``."""
    runs = len(next(iter(member.per_run.values()), []))
    per_run_labels: list[dict[str, str]] = []
    per_run_near: list[set[str]] = []
    taus: list[float | None] = []
    for r in range(runs):
        tau, labels, near = threshold_labels(
            {name: values[r] for name, values in member.per_run.items()}, config
        )
        taus.append(tau)
        per_run_labels.append(labels)
        per_run_near.append(near)

    rows: list[dict[str, Any]] = []
    for name in sorted(member.per_run):
        values = member.per_run[name]
        scored = [value for value in values if value is not None]
        run_labels = [labels_r[name] for labels_r in per_run_labels]
        judged = {label for label in run_labels if label != "unscored"}
        borderline = name in member.borderline or any(name in near_r for near_r in per_run_near)
        row: dict[str, Any] = {"creation_id": name}
        for r, value in enumerate(values, start=1):
            row[f"s_{r}"] = value
        row.update(
            mean=statistics.fmean(scored) if scored else None,
            sd=statistics.stdev(scored) if len(scored) > 1 else None,
            cv=coefficient_of_variation(scored),
            labels=" ".join(label[0] if label != "unscored" else "-" for label in run_labels),
            label_changed=len(judged) > 1,
            borderline=borderline,
            exempt=name in exempt,
        )
        rows.append(row)
    return rows, taus


def chunk_cvs(member: MemberScores) -> list[float | None]:
    """Each chunk's coefficient of variation across the runs (failed runs left out)."""
    return [
        coefficient_of_variation([value for value in values if value is not None])
        for _, values in sorted(member.chunk_deltas.items())
    ]


def m_rows(member: MemberScores, config: Config, exempt: set[str]) -> list[dict[str, Any]]:
    """For each ``m`` in ``M_values``: the labels from the first ``m`` runs against all ``M``."""
    runs = len(next(iter(member.per_run.values()), []))
    _, full_labels, full_near = threshold_labels(dict(member.score), config)
    rows: list[dict[str, Any]] = []
    for m in sorted(set(config.experiment.sensitivity.M_values)):
        means: dict[str, float | None] = {}
        for name, values in member.per_run.items():
            scored = [value for value in values[:m] if value is not None]
            means[name] = statistics.fmean(scored) if scored else None
        _, labels, near = threshold_labels(means, config)
        judged = [
            name
            for name in sorted(labels)
            if name not in exempt and name not in near and name not in full_near
        ]
        changed = [name for name in judged if labels[name] != full_labels[name]]
        rows.append(
            {
                "M": m,
                "of_M": runs,
                "n_compared": len(judged),
                "n_changed": len(changed),
                "changed": " ".join(changed),
                "agrees": not changed,
            }
        )
    return rows


def p_sweep_rows(members: Sequence[MemberScores], exempt: set[str]) -> list[dict[str, Any]]:
    """Question (b): each creation's score and label at every ``P``."""
    names = sorted(set().union(*(member.label for member in members)))
    rows: list[dict[str, Any]] = []
    for name in names:
        row: dict[str, Any] = {"creation_id": name}
        labels: set[str] = set()
        near = False
        for member in members:
            row[f"score_P{member.P}"] = member.score.get(name)
            label = member.label.get(name, "unscored")
            row[f"label_P{member.P}"] = label
            if label != "unscored":
                labels.add(label)
            near = near or name in member.borderline
        row.update(label_changed=len(labels) > 1, borderline=near, exempt=name in exempt)
        rows.append(row)
    return rows


def verdict(rows: Sequence[dict[str, Any]]) -> tuple[str, list[str], int]:
    """``(verdict, changed, judged)`` over the creations neither borderline nor exempt."""
    judged = [row for row in rows if not row["borderline"] and not row["exempt"]]
    changed = [row["creation_id"] for row in judged if row["label_changed"]]
    if not judged:
        return UNDEFINED, [], 0
    return (FAIL if changed else PASS), changed, len(judged)


def recommend_m(
    m_table: Sequence[dict[str, Any]], unstable_share: float | None, max_unstable: float, runs: int
) -> str:
    """The book's rule made explicit: raise ``M`` when too many chunks vary, else the cheapest ``M``."""
    if unstable_share is not None and unstable_share > max_unstable:
        return (
            f"raise M above {runs}: {unstable_share:.1%} of chunks vary across runs by more than the "
            f"calibration bound, above the {max_unstable:.0%} the book tolerates; repeat the sweep"
        )
    agreeing = [row["M"] for row in m_table if row["agrees"]]
    if not agreeing:
        return f"keep M = {runs}: no smaller M reproduces its labels"
    return f"M = {min(agreeing)}: the smallest M whose labels agree with all {runs} runs"


# ---------------------------------------------------------------------------------------- the run


@dataclass
class SweepResult:
    """Everything the sweep concluded, as written to ``sensitivity.json``."""

    sweep_id: str
    sweep_dir: Path
    verdict: str
    stability: str
    p_sweep: str
    recommendation: str
    details: dict[str, Any] = field(default_factory=dict)


def run_sweep(config: Config, sweep_id: str = "", *, progress: bool = True) -> SweepResult:
    """Run (or resume) one pipeline run per ``P``, then write the tables and the verdict."""
    sweep_id = sweep_id or build_run_id(config)
    values = _sweep_values(config)
    out = config.path(config.run.out_dir)
    sweep_dir = out / sweep_id
    if is_complete(sweep_dir):
        raise SensitivityError(f"sweep '{sweep_id}' is already complete at {sweep_dir} (R9)")

    for size in values:
        run_id = member_run_id(sweep_id, size)
        if is_complete(out / run_id):
            logger.info("sensitivity.reuse", run_id=run_id)
            continue
        logger.info("sensitivity.run", run_id=run_id, P=size)
        execute_run(member_config(config, size), run_id=run_id, progress=progress)

    return analyse_sweep(
        config, sweep_id, {size: out / member_run_id(sweep_id, size) for size in values}
    )


def analyse_sweep(config: Config, sweep_id: str, run_dirs: dict[int, Path]) -> SweepResult:
    """Read the finished runs of a sweep and write its tables, verdict and summary."""
    sweep_dir = config.path(config.run.out_dir) / sweep_id
    sweep_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(log_file=sweep_dir / "logs" / "run.log")
    started = datetime.now(UTC)
    (sweep_dir / "config.snapshot.yaml").write_text(
        yaml.safe_dump(config.to_dict(), sort_keys=True), encoding="utf-8", newline="\n"
    )

    sensitivity = config.experiment.sensitivity
    exempt = set(sensitivity.exempt)
    members = [read_member(run_dirs[size], size, config.run.M) for size in sorted(run_dirs)]
    reference = next(member for member in members if member.P == config.chunking.P)

    stability, taus = stability_rows(reference, config, exempt)
    cvs = chunk_cvs(reference)
    measured = [cv for cv in cvs if cv is not None]
    max_cv = config.experiment.calibration.max_cv
    unstable_share = sum(1 for cv in measured if cv > max_cv) / len(measured) if measured else None
    m_table = m_rows(reference, config, exempt)
    sweep = p_sweep_rows(members, exempt)

    verdict_a, changed_a, judged_a = verdict(stability)
    verdict_b, changed_b, judged_b = verdict(sweep)
    overall = (
        FAIL
        if FAIL in (verdict_a, verdict_b)
        else PASS
        if verdict_a == verdict_b == PASS
        else UNDEFINED
    )
    recommendation = recommend_m(
        m_table, unstable_share, 1 - config.experiment.calibration.min_stable_share, config.run.M
    )

    _table(sweep_dir / "stability.csv", stability)
    _table(sweep_dir / "m_check.csv", m_table)
    _table(sweep_dir / "p_sweep.csv", sweep)
    _table(
        sweep_dir / "chunk_cv.csv",
        [
            {"creation_id": name, "chunk_index": index, "cv": cv}
            for (name, index), cv in zip(sorted(reference.chunk_deltas), cvs, strict=True)
        ],
    )

    result = SweepResult(
        sweep_id=sweep_id,
        sweep_dir=sweep_dir,
        verdict=overall,
        stability=(
            f"{verdict_a}: {len(changed_a)} of {judged_a} judged creations changed label across "
            f"the {config.run.M} runs at P = {config.chunking.P}"
        ),
        p_sweep=(
            f"{verdict_b}: {len(changed_b)} of {judged_b} judged creations changed label across "
            f"P = {', '.join(str(member.P) for member in members)}"
        ),
        recommendation=recommendation,
        details={
            "reference_P": config.chunking.P,
            "M": config.run.M,
            "runs": {member.P: member.run_id for member in members},
            "exempt": sorted(exempt),
            "changed_across_runs": changed_a,
            "changed_across_P": changed_b,
            "per_run_tau": taus,
            "tau_by_P": {member.P: member.tau for member in members},
            "chunks_measured": len(measured),
            "chunk_cv_median": statistics.median(measured) if measured else None,
            "chunk_cv_max": max(measured) if measured else None,
            "unstable_chunk_share": unstable_share,
            "cv_bound": max_cv,
            "m_check": m_table,
            "noise_enabled": config.noise.enabled,
        },
    )
    payload = asdict(result)
    payload["sweep_dir"] = str(sweep_dir)
    _dump(sweep_dir / "sensitivity.json", payload)
    (sweep_dir / "summary.md").write_text(render_summary(result), encoding="utf-8", newline="\n")
    _dump(
        sweep_dir / "manifest.json",
        {
            "run_id": sweep_id,
            "experiment": "sensitivity",
            "started_utc": started.isoformat(),
            "ended_utc": datetime.now(UTC).isoformat(),
            "config_hash": config.config_hash(),
            "seed": config.run.seed,
            "members": {member.P: member.run_id for member in members},
            **_code_version(config.root),
            "verdict": overall,
        },
    )
    logger.info("sensitivity.complete", sweep_id=sweep_id, verdict=overall)
    return result


def _table(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """A CSV table; an empty cell is a value that does not exist."""
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if value is None else value for key, value in row.items()})


def render_summary(result: SweepResult) -> str:
    """The sweep's written result, as markdown."""
    details = result.details
    share = details["unstable_chunk_share"]
    noise = (
        "Runs 2 to M each inject one foreign creation, as the main proposal does, so the runs "
        "differ by that text as well as by the model's own variation."
        if details["noise_enabled"]
        else "Noise injection is off, so the runs differ only by the model's own variation."
    )
    return "\n".join(
        [
            "# Reproducibility and sensitivity (M11)",
            "",
            f"Sweep `{result.sweep_id}`. `docs/EXPERIMENTS.md` Stage 2, success metric 1.",
            "",
            f"**Verdict: {result.verdict}.**",
            "",
            "| | |",
            "|---|---|",
            f"| (a) across the runs | {result.stability} |",
            f"| (b) across P | {result.p_sweep} |",
            f"| chunks whose CV exceeds {details['cv_bound']} | "
            + (
                f"{share:.1%} of {details['chunks_measured']}"
                if share is not None
                else "none measured"
            )
            + " |",
            f"| recommendation | {result.recommendation} |",
            "",
            "Passes if no creation changes label, except one that is borderline in some run or at",
            f"some P, or exempt: {', '.join(details['exempt']) or 'none'}.",
            "",
            noise,
            "",
            "`stability.csv` holds each creation's per-run scores, mean, SD, CV and per-run labels",
            "(a = authentic, s = suspicious); `chunk_cv.csv` every chunk's CV across the runs;",
            "`m_check.csv` the labels from the first M runs against all of them; `p_sweep.csv`",
            "each creation's score and label at every P. Each P is an ordinary run directory,",
            "listed in `sensitivity.json`.",
            "",
        ]
    )


__all__ = [
    "MemberScores",
    "SensitivityError",
    "SweepPlan",
    "SweepResult",
    "analyse_sweep",
    "chunk_cvs",
    "m_rows",
    "member_config",
    "member_run_id",
    "p_sweep_rows",
    "plan_sweep",
    "read_member",
    "recommend_m",
    "run_sweep",
    "stability_rows",
    "threshold_labels",
    "verdict",
]
