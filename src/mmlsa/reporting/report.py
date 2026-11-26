"""The final report of a run (milestone M15): ``python -m mmlsa report --run-id R``.

One markdown file, ``report.md``, with the tables behind it as CSV and the run's figures beside it,
written to ``reports/<run_id>/`` rather than into the run directory, which is immutable (R9). The
report is derived: it can be regenerated at any time from the run and costs no call.

It carries, in order:

* what the run was (model, ``M``, ``P``, seed, noise, commit, calls and tokens);
* the threshold and its bimodality diagnostics, and the sorted scores with labels;
* **success metric 1**, label stability across the ``M`` runs (``experiments/sensitivity.py``);
* **success metric 3**, agreement with the consensus cases (``data/consensus_cases.yaml``);
* the agreement table against the prior study's findings (``data/prior_findings.yaml``), reported
  both ways, agreements and disagreements, and marked incomplete while that list is;
* the injected noise texts and where they landed;
* the verdicts of any experiment runs passed with ``--include`` (the control experiment, which is
  success metric 2, the validation checks and the sensitivity sweep).

The two data files judge the result and are read nowhere else: no profile, threshold or decision in
the pipeline depends on them (``docs/DATA.md`` section 3).
"""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mmlsa.config import Config
from mmlsa.experiments.sensitivity import read_member, stability_rows, verdict
from mmlsa.pipeline.classify import AUTHENTIC, SUSPICIOUS
from mmlsa.pipeline.orchestrator import is_complete
from mmlsa.reporting.release import snapshot_config


class ReportError(Exception):
    """Raised when a report cannot be built from what is on disk."""


# --------------------------------------------------------------------------------- the judgements


@dataclass(frozen=True)
class ConsensusResult:
    """Success metric 3: how many consensus cases the run classified as expected."""

    rows: list[dict[str, Any]]
    n_correct: int
    n_cases: int
    min_correct: int

    @property
    def verdict(self) -> str:
        """``pass`` when at least ``min_correct`` cases are right."""
        return "pass" if self.n_correct >= self.min_correct else "fail"


def consensus_agreement(
    labels: dict[str, str], scores: dict[str, float | None], cases: dict[str, Any]
) -> ConsensusResult:
    """Compare the run's labels with the consensus cases."""
    expected = cases.get("expected_label", SUSPICIOUS)
    rows: list[dict[str, Any]] = []
    for case in cases.get("cases", []):
        name = case["id"]
        label = labels.get(name, "not in run")
        rows.append(
            {
                "creation_id": name,
                "co_author": case.get("co_author", ""),
                "score": scores.get(name),
                "label": label,
                "expected": expected,
                "correct": label == expected,
                "citation": case.get("citation", ""),
            }
        )
    return ConsensusResult(
        rows=rows,
        n_correct=sum(1 for row in rows if row["correct"]),
        n_cases=len(rows),
        min_correct=int(cases.get("min_correct", len(rows))),
    )


@dataclass(frozen=True)
class PriorAgreement:
    """The agreement table against the prior study, both ways."""

    rows: list[dict[str, Any]]
    counts: dict[str, int]
    complete: bool
    kappa: float | None
    """Cohen's kappa over the creations both classified; only when the prior list is complete."""


def prior_agreement(labels: dict[str, str], prior: dict[str, Any]) -> PriorAgreement:
    """Cross the run's labels with the prior study's flagged set.

    While the prior list is incomplete, only the creations it names can be compared: a creation it
    does not name may be one of its missing flags, so it is reported as unknown, not as authentic.
    """
    flagged = set(prior.get("flagged", []))
    complete = bool(prior.get("complete", False))
    rows: list[dict[str, Any]] = []
    counts = {"both_suspicious": 0, "both_authentic": 0, "only_ours": 0, "only_prior": 0}
    for name in sorted(labels):
        ours = labels[name]
        if name in flagged:
            theirs = SUSPICIOUS
        elif complete:
            theirs = AUTHENTIC
        else:
            theirs = "unknown"
        agree: bool | None = None
        if theirs != "unknown" and ours in (SUSPICIOUS, AUTHENTIC):
            agree = ours == theirs
            if ours == theirs == SUSPICIOUS:
                counts["both_suspicious"] += 1
            elif ours == theirs == AUTHENTIC:
                counts["both_authentic"] += 1
            elif ours == SUSPICIOUS:
                counts["only_ours"] += 1
            else:
                counts["only_prior"] += 1
        rows.append({"creation_id": name, "ours": ours, "prior": theirs, "agree": agree})
    return PriorAgreement(
        rows=rows,
        counts=counts,
        complete=complete,
        kappa=cohens_kappa(counts) if complete else None,
    )


def cohens_kappa(counts: dict[str, int]) -> float | None:
    """Cohen's kappa of two binary labelings from their 2x2 table; None when undefined."""
    a, d = counts["both_suspicious"], counts["both_authentic"]
    b, c = counts["only_ours"], counts["only_prior"]
    n = a + b + c + d
    if n == 0:
        return None
    observed = (a + d) / n
    expected = ((a + b) * (a + c) + (c + d) * (b + d)) / (n * n)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


# --------------------------------------------------------------------------------------- the run


@dataclass
class RunFacts:
    """What the report reads from a finished run directory."""

    run_id: str
    run_dir: Path
    manifest: dict[str, Any]
    threshold: dict[str, Any]
    scores: list[dict[str, str]]
    noise: list[dict[str, str]] = field(default_factory=list)


def read_run(run_dir: Path) -> RunFacts:
    """Read a finished run's manifest, threshold, scores and noise diagnostics."""
    if not is_complete(run_dir):
        raise ReportError(f"{run_dir} is not a finished run")

    def table(name: str) -> list[dict[str, str]]:
        path = run_dir / name
        if not path.is_file():
            return []
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    return RunFacts(
        run_id=run_dir.name,
        run_dir=run_dir,
        manifest=json.loads((run_dir / "manifest.json").read_text(encoding="utf-8")),
        threshold=json.loads((run_dir / "threshold.json").read_text(encoding="utf-8")),
        scores=table("scores.csv"),
        noise=table("noise_diagnostics.csv"),
    )


def is_finished_experiment(run_dir: Path) -> bool:
    """Whether a directory holds a finished experiment run.

    The control experiment records ``finished_utc`` where every other run records ``ended_utc``.
    """
    path = run_dir / "manifest.json"
    if not path.is_file():
        return False
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(manifest.get("experiment")) and bool(
        manifest.get("ended_utc") or manifest.get("finished_utc")
    )


def _control_headline(result: dict[str, Any]) -> str:
    stats = result.get("statistics") or {}
    return (
        f"{stats.get('n', 0)} paired chunks, mean delta A - B "
        f"{_figure(stats.get('mean_difference'))}, one-sided p {_figure(stats.get('p_less'))}, "
        f"d_z {_figure(stats.get('cohens_d'), 2)}"
    )


def experiment_line(run_dir: Path) -> dict[str, str]:
    """One experiment run's name, verdict and headline, from its own result file."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    name = str(manifest.get("experiment", ""))
    path = run_dir / f"{name}.json"
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if name == "control":
        headline = _control_headline(result)
    elif name == "sensitivity":
        headline = "; ".join(
            str(result[key])
            for key in ("stability", "p_sweep", "recommendation")
            if result.get(key)
        )
    else:
        headline = str(result.get("measured", ""))
    return {
        "experiment": name,
        "run_id": run_dir.name,
        "verdict": str(manifest.get("verdict") or result.get("verdict") or ""),
        "headline": headline,
    }


# ------------------------------------------------------------------------------------ the report


@dataclass
class Report:
    """A built report and where it was written."""

    out_dir: Path
    consensus: ConsensusResult
    prior: PriorAgreement
    stability_verdict: str
    experiments: list[dict[str, str]]


def _number(text: str | None) -> float | None:
    return float(text) if text not in (None, "") else None


def build_report(
    config: Config,
    run_id: str,
    *,
    out_dir: Path | None = None,
    include: Sequence[str] = (),
) -> Report:
    """Write ``report.md``, its tables and the run's figures to ``reports/<run_id>/``."""
    runs = config.path(config.run.out_dir)
    facts = read_run(runs / run_id)
    out = out_dir or config.root / "reports" / run_id
    out.mkdir(parents=True, exist_ok=True)

    labels = {row["creation_id"]: row["label"] for row in facts.scores}
    scores = {row["creation_id"]: _number(row["score_mean"]) for row in facts.scores}

    consensus = consensus_agreement(
        labels, scores, _yaml(config.path(config.report.consensus_cases))
    )
    prior_data = _yaml(config.path(config.report.compare_to_prior))
    prior = prior_agreement(labels, prior_data)

    # The run is re-thresholded per run under its own settings, not today's; which creations are
    # exempt is a judgement made at report time, so it comes from the configuration in hand.
    own = snapshot_config(config, facts.run_dir)
    member = read_member(facts.run_dir, own.chunking.P, own.run.M)
    exempt = set(config.experiment.sensitivity.exempt)
    stability, _ = stability_rows(member, own, exempt)
    stable_verdict, changed, judged = verdict(stability)

    experiments = []
    for other in include:
        if not is_finished_experiment(runs / other):
            raise ReportError(f"--include {other}: no finished experiment run under {runs}")
        experiments.append(experiment_line(runs / other))

    _write(
        out / "scores.csv", sorted(facts.scores, key=lambda row: _number(row["score_mean"]) or 0.0)
    )
    _write(out / "stability.csv", stability)
    _write(out / "consensus.csv", consensus.rows)
    _write(out / "prior_agreement.csv", prior.rows)
    figures = facts.run_dir / "figures"
    if figures.is_dir():
        shutil.copytree(figures, out / "figures", dirs_exist_ok=True)

    text = render(
        facts,
        consensus,
        prior,
        prior_data,
        (stable_verdict, changed, judged, sorted(exempt)),
        experiments,
        has_figures=figures.is_dir(),
    )
    (out / "report.md").write_text(text, encoding="utf-8", newline="\n")
    return Report(
        out_dir=out,
        consensus=consensus,
        prior=prior,
        stability_verdict=stable_verdict,
        experiments=experiments,
    )


def _yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ReportError(f"{path} is missing; the report judges the run against it")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if value is None else value for key, value in row.items()})


def _figure(value: Any, digits: int = 4) -> str:
    if value in (None, ""):
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def render(
    facts: RunFacts,
    consensus: ConsensusResult,
    prior: PriorAgreement,
    prior_data: dict[str, Any],
    stability: tuple[str, list[str], int, list[str]],
    experiments: list[dict[str, str]],
    *,
    has_figures: bool,
) -> str:
    """The report as markdown."""
    manifest, threshold = facts.manifest, facts.threshold
    calls = manifest.get("calls", {})
    noise = manifest.get("noise", {})
    stable_verdict, changed, judged, exempt = stability
    lines = [
        f"# Run report: `{facts.run_id}`",
        "",
        "| | |",
        "|---|---|",
        f"| model | {manifest.get('provider', '')} `{manifest.get('model_id', '')}` |",
        f"| M runs, chunk length P | {manifest.get('M', '')}, {manifest.get('P', '')} words |",
        f"| distance, classifier | {manifest.get('distance_metric', '')}, {manifest.get('classifier', '')} |",
        f"| seed | {manifest.get('seed', '')} |",
        f"| noise injection | {'on: ' + ', '.join(noise.get('injected', [])) if noise.get('enabled') else 'off'} |",
        f"| code | `{str(manifest.get('git_commit', ''))[:12]}` |",
        f"| calls | {calls.get('total', 0):,} ({calls.get('live', 0):,} live, {calls.get('cached', 0):,} from the cache) |",
        f"| tokens | {calls.get('input_tokens', 0):,} in, {calls.get('output_tokens', 0):,} out |",
        "",
        "## The threshold",
        "",
        f"`tau` = {_figure(threshold.get('tau'))} by {threshold.get('method', '')}: "
        f"{threshold.get('n_suspicious', 0)} suspicious, {threshold.get('n_authentic', 0)} authentic"
        + (
            ", borderline: " + ", ".join(threshold.get("borderline", []))
            if threshold.get("borderline")
            else ""
        )
        + ".",
        "",
        "**The bimodality check raised a flag: inspect the histogram and consider the fallback "
        "(`docs/OPEN_QUESTIONS.md` Q9).**"
        if threshold.get("flagged")
        else "The bimodality check raised no flag.",
        "",
    ]
    if has_figures:
        lines += [
            "![Sorted scores with tau](figures/sorted_scatter.png)",
            "",
            "![Histogram of the scores](figures/histogram.png)",
            "",
        ]
    lines += [
        "## Scores",
        "",
        "| creation | score | SD over runs | label | borderline | unreliable |",
        "|---|---|---|---|---|---|",
    ]
    for row in sorted(facts.scores, key=lambda row: -(_number(row["score_mean"]) or 0.0)):
        lines.append(
            f"| {row.get('title') or row['creation_id']} | {_figure(row['score_mean'])} | "
            f"{_figure(row.get('score_std'))} | {row['label']} | "
            f"{'yes' if row.get('borderline') == 'True' else ''} | "
            f"{'yes' if row.get('unreliable') == 'True' else ''} |"
        )

    lines += [
        "",
        "## Success metric 1: stable labels across the runs",
        "",
        f"**{stable_verdict}.** {len(changed)} of {judged} judged creations changed label across "
        f"the {manifest.get('M', '')} runs"
        + (f": {', '.join(changed)}" if changed else "")
        + f". Each run is thresholded on its own scores; exempt: {', '.join(exempt) or 'none'}, "
        "and any creation borderline in some run. Per-run labels are in `stability.csv`.",
        "",
        "## Success metric 3: agreement with the consensus cases",
        "",
        f"**{consensus.verdict}.** {consensus.n_correct} of {consensus.n_cases} classified as "
        f"{consensus.rows[0]['expected'] if consensus.rows else 'expected'}; at least "
        f"{consensus.min_correct} are required.",
        "",
        "| creation | co-author | score | label | correct |",
        "|---|---|---|---|---|",
        *[
            f"| {row['creation_id']} | {row['co_author']} | {_figure(row['score'])} | {row['label']} | "
            f"{'yes' if row['correct'] else 'no'} |"
            for row in consensus.rows
        ],
        "",
        "## Agreement with the prior study",
        "",
        f"{prior_data.get('source', '')}, {prior_data.get('model', '')} model, "
        f"{prior_data.get('n_flagged', '?')} flagged.",
        "",
    ]
    counts = prior.counts
    if not prior.complete:
        lines += [
            f"**The prior list is incomplete:** {len(prior_data.get('flagged', []))} of its "
            f"{prior_data.get('n_flagged', '?')} flagged works are recorded, so only those can be "
            "compared, and a creation it does not name is unknown rather than authentic "
            "(`docs/OPEN_QUESTIONS.md` Q23).",
            "",
        ]
    lines += [
        "| | prior: suspicious | prior: authentic |",
        "|---|---|---|",
        f"| ours: suspicious | {counts['both_suspicious']} | {counts['only_ours']} |",
        f"| ours: authentic | {counts['only_prior']} | {counts['both_authentic']} |",
        "",
        f"Cohen's kappa: {_figure(prior.kappa, 3)}. Agreements and disagreements are both reported; "
        "the prior study is a comparison, not ground truth. Every creation is in "
        "`prior_agreement.csv`.",
        "",
    ]
    if facts.noise:
        lines += [
            "## The injected noise texts",
            "",
            "Scored as a diagnostic, never part of `tau`: a foreign text should land above it.",
            "",
            "| run | text | score | above tau |",
            "|---|---|---|---|",
            *[
                f"| {row['run_index']} | {row.get('title') or row['creation_id']} | "
                f"{_figure(row['score'])} | {'yes' if row.get('above_tau') == '1' else 'no'} |"
                for row in facts.noise
            ],
            "",
        ]
    if experiments:
        lines += [
            "## Experiments on this run",
            "",
            "| experiment | run | verdict | measured |",
            "|---|---|---|---|",
            *[
                f"| {row['experiment']} | `{row['run_id']}` | {row['verdict']} | {row['headline']} |"
                for row in experiments
            ],
            "",
        ]
    lines += [
        "---",
        "",
        f"Generated from `runs/{facts.run_id}/` by `python -m mmlsa report`. Every number traces to "
        "the run's `scores.csv`, `deltas/` and `calls.jsonl` (R7).",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "ConsensusResult",
    "PriorAgreement",
    "Report",
    "ReportError",
    "build_report",
    "cohens_kappa",
    "consensus_agreement",
    "experiment_line",
    "is_finished_experiment",
    "prior_agreement",
    "read_run",
    "render",
]
