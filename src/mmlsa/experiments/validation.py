"""The four validation checks of ``docs/SPEC.md`` section 7 (milestone M14).

Each check runs against a **baseline**: a finished run of record, read from ``runs/<run_id>/``. Its
profiles and its threshold ``tau`` are reused, so a check adds calls only for what is new, and what
it measures is the pipeline that produced the results being validated (``docs/DECISIONS.md`` I39).

* **Calibration.** A stratified sample of the corpus's chunks is rewritten ``repeats`` times under
  the baseline's run 1 profile, all else constant. Each chunk's coefficient of variation (CV) of its
  deltas is measured; the check passes when the share of chunks with ``CV <= max_cv`` reaches
  ``min_stable_share``, the spec's "large majority" made a number (``OPEN_QUESTIONS.md`` Q21).
* **Synthetic mixture.** ``splice_words`` consecutive words of a mixture source replace the same
  number of words of a clearly authentic creation, at a seeded position. Replacing rather than
  inserting keeps every chunk boundary, so the chunks the splice does not touch are the baseline's own
  and come from the cache. The check passes when every spliced creation lands above ``tau`` **and**
  its per-chunk delta (the mean over the runs) peaks within ``tolerance_chunks`` of the splice.
* **Held-out generalization.** The reserved texts (``data/heldout``) are chunked and rewritten under
  each of the baseline's run profiles and scored as Step 5 scores a creation. The check passes when
  every one is labelled as its ``expected_label`` says.
* **Noise robustness.** A run with noise injection is compared with the same run without it
  (``noise.enabled=false``). The check passes when no creation that is borderline in neither run
  changes its label. It reads two finished runs and makes no calls.

The scored texts are never profiled and never move ``tau``: like the injected noise text in a run,
they are judged by the pipeline, not part of it (``data/corpus_sources.yaml``).

Every check writes an immutable directory: ``<check>.json`` with the verdict, the measured value
next to its condition, and the baseline it was measured against; ``summary.md``; the per-chunk table
behind the number (R7); and, for the checks that call a model, ``calls.jsonl`` and the rewrites.
"""

from __future__ import annotations

import csv
import json
import random
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from mmlsa.chunking import Chunk, chunk_text, split_words
from mmlsa.config import Config
from mmlsa.corpus.loader import directories_from_config, load_sources, load_text
from mmlsa.distance.registry import build_distance
from mmlsa.distance.tokenize import load_function_words
from mmlsa.experiments.control import _chunk, _load_texts, _validation, select_control_sample
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger, read_ledger, summarize
from mmlsa.llm.providers import build_provider, default_model
from mmlsa.llm.runner import Runner
from mmlsa.pipeline.classify import AUTHENTIC, SUSPICIOUS
from mmlsa.pipeline.orchestrator import (
    RESUMABLE_KEYS,
    _code_version,
    _dump,
    _flatten,
    _write_chunks,
    _write_deltas,
    _write_rewrites,
    build_run_id,
    is_complete,
)
from mmlsa.pipeline.profile import StyleProfile
from mmlsa.pipeline.rewrite import ChunkRewrite, rewrite_chunks, to_chunk_deltas
from mmlsa.pipeline.score import CreationScore, aggregate_creation, aggregate_run
from mmlsa.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)

CHECKS = ("calibration", "mixture", "heldout", "noise")

PASS, FAIL, UNDEFINED = "pass", "fail", "undefined"


class CheckError(Exception):
    """Raised when a validation check cannot be set up against its baseline."""


# --------------------------------------------------------------------------------- the baseline


FREE_PREFIXES = ("experiment.", "report.")
"""Keys a check may set differently from its baseline: they change no answer and no score."""

FREE_KEYS = frozenset({"llm.mode"}) | RESUMABLE_KEYS


@dataclass(frozen=True)
class Baseline:
    """What a check reuses from a finished run of record."""

    run_id: str
    run_dir: Path
    M: int
    tau: float
    profiles: dict[int, str]
    """The rendered profile of each run, by run index."""
    scores: dict[str, float | None]
    labels: dict[str, str]
    borderline: frozenset[str]


def _read_snapshot(run_dir: Path) -> dict[str, Any]:
    """A run's configuration as it was when the run started."""
    snapshot = run_dir / "config.snapshot.yaml"
    if not snapshot.is_file():
        raise CheckError(f"{run_dir} has no config.snapshot.yaml, so it is not a run directory")
    return yaml.safe_load(snapshot.read_text(encoding="utf-8")) or {}


def method_differences(
    snapshot: dict[str, Any], current: dict[str, Any], *, also_free: Sequence[str] = ()
) -> list[str]:
    """The keys that differ between two configurations and would change an answer or a score."""
    before, after = _flatten(snapshot), _flatten(current)
    free = FREE_KEYS | set(also_free)
    return sorted(
        key
        for key in before.keys() | after.keys()
        if key not in free
        and not key.startswith(FREE_PREFIXES)
        and not any(key.startswith(f"{prefix}.") for prefix in also_free)
        and before.get(key) != after.get(key)
    )


def _read_scores(run_dir: Path) -> tuple[dict[str, float | None], dict[str, str], set[str]]:
    """Scores, labels and the borderline set from a run's ``scores.csv``."""
    scores: dict[str, float | None] = {}
    labels: dict[str, str] = {}
    borderline: set[str] = set()
    with (run_dir / "scores.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = row["creation_id"]
            scores[name] = float(row["score_mean"]) if row["score_mean"] else None
            labels[name] = row["label"]
            if row.get("borderline", "").strip().lower() in {"true", "1"}:
                borderline.add(name)
    return scores, labels, borderline


def _finished_run(config: Config, run_id: str) -> Path:
    """The directory of a finished run, or a clear refusal."""
    run_dir = config.path(config.run.out_dir) / run_id
    if not is_complete(run_dir):
        raise CheckError(
            f"no finished run '{run_id}' under {config.path(config.run.out_dir)}. A check needs a "
            "completed run of record as its baseline: python -m mmlsa run --config <same config>."
        )
    return run_dir


def load_baseline(config: Config, run_id: str) -> Baseline:
    """Read a finished run and confirm the check runs under the same method parameters."""
    run_dir = _finished_run(config, run_id)
    differing = method_differences(_read_snapshot(run_dir), config.to_dict())
    if differing:
        raise CheckError(
            f"the configuration differs from baseline '{run_id}' in {', '.join(differing)}. A check "
            "must measure the pipeline that produced the baseline: pass the same --config and --set "
            "options as that run."
        )

    profiles: dict[int, str] = {}
    for run_index in range(1, config.run.M + 1):
        path = run_dir / "profiles" / f"run_{run_index}_merged.json"
        if not path.is_file():
            raise CheckError(f"baseline '{run_id}' has no profile for run {run_index} ({path})")
        payload = json.loads(path.read_text(encoding="utf-8"))
        profiles[run_index] = StyleProfile(
            fields=payload.get("fields") or {},
            free_text=payload.get("free_text", ""),
            structured=payload.get("structured", True),
        ).render()

    threshold = json.loads((run_dir / "threshold.json").read_text(encoding="utf-8"))
    scores, labels, borderline = _read_scores(run_dir)
    return Baseline(
        run_id=run_id,
        run_dir=run_dir,
        M=config.run.M,
        tau=float(threshold["tau"]),
        profiles=profiles,
        scores=scores,
        labels=labels,
        borderline=frozenset(borderline),
    )


def label_for(score: float | None, tau: float, band: float) -> tuple[str, bool]:
    """Step 6 for a text scored against a fixed ``tau``: its label and whether it is borderline.

    The same rule as ``classify``: strictly above ``tau`` is suspicious, and within ``band`` of it is
    also reported as borderline. A text with no score has the label ``unscored``.
    """
    if score is None:
        return "unscored", False
    return (SUSPICIOUS if score > tau else AUTHENTIC), abs(score - tau) <= band


# ------------------------------------------------------------------------------------ the result


@dataclass
class CheckResult:
    """One check's outcome, as written to ``<check>.json``."""

    check: str
    run_id: str
    run_dir: Path
    baseline: str
    verdict: str
    measured: str
    """The measured value, in words, printed next to the condition."""
    condition: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """The result as JSON-ready values, without the per-row table."""
        payload = asdict(self)
        payload["run_dir"] = str(self.run_dir)
        payload.pop("rows")
        return payload


# ------------------------------------------------------------------------- shared experiment setup


@dataclass
class _Session:
    """The open run directory and the call path of one check."""

    run_id: str
    run_dir: Path
    started: datetime
    code: dict[str, Any]
    runner: Runner | None = None
    provider: Any = None
    function_words: frozenset[str] = frozenset()
    distance: Any = None


def _open(config: Config, check: str, *, calls: bool, progress: bool = True) -> _Session:
    """Create the check's run directory and, when it calls a model, its runner and ledger."""
    run_id = build_run_id(config, tag=check)
    run_dir = config.path(config.run.out_dir) / run_id
    if run_dir.exists():
        raise CheckError(
            f"'{run_id}' already exists at {run_dir}. Run artifacts are immutable (R9); wait a "
            "minute for a new run id. The cache answers every call the earlier attempt made."
        )
    run_dir.mkdir(parents=True)
    configure_logging(log_file=run_dir / "logs" / "run.log")
    started = datetime.now(UTC)
    (run_dir / "config.snapshot.yaml").write_text(
        yaml.safe_dump(config.to_dict(), sort_keys=True), encoding="utf-8", newline="\n"
    )
    code = _code_version(config.root)
    _dump(run_dir / "code_version.json", {**code, "started_utc": started.isoformat()})
    session = _Session(run_id=run_id, run_dir=run_dir, started=started, code=code)
    if not calls:
        return session

    words_path = str(config.path(config.distance.function_words))
    session.function_words = frozenset(load_function_words(words_path))
    session.distance = build_distance(config.distance.metric, words_path)
    cache = ResponseCache(config.path(config.llm.cache_dir), mode=config.llm.mode)
    session.provider = build_provider(
        config.llm.provider,
        model_id=config.llm.model_id,
        cache=cache,
        timeout_seconds=config.llm.timeout_seconds,
    )
    session.runner = Runner(
        provider=session.provider,
        cache=cache,
        ledger=Ledger(run_dir / "calls.jsonl", run_id=run_id),
        concurrency=config.llm.concurrency,
        requests_per_minute=config.llm.requests_per_minute,
        tokens_per_minute=config.llm.tokens_per_minute,
        max_transient_retries=config.llm.max_transient_retries,
        mode=config.llm.mode,
        progress=progress,
    )
    return session


def _rewrite(
    config: Config, session: _Session, chunks: list[Chunk], profile: str, run_index: int
) -> list[ChunkRewrite]:
    """Step 3 for some chunks, exactly as a run issues it for this profile and run index."""
    assert session.runner is not None
    return rewrite_chunks(
        chunks,
        profile,
        session.runner,
        session.function_words,
        run_index=run_index,
        validation=_validation(config),
        max_retries=config.rewrite.max_retries,
        max_output_tokens=config.rewrite.max_output_tokens,
        temperature=config.llm.temperature,
    )


def score_under_baseline(
    config: Config,
    session: _Session,
    baseline: Baseline,
    chunks: dict[str, list[Chunk]],
) -> tuple[dict[str, CreationScore], dict[str, list[list[float | None]]]]:
    """Steps 3 to 5 for texts outside the corpus, under each of the baseline's run profiles.

    Returns each text's creation score and, per text, every chunk's delta in every run (``None``
    where the rewrite failed). The rewrites and deltas are written per run, as a run writes them.
    """
    per_run: dict[str, list[Any]] = {name: [] for name in chunks}
    by_chunk: dict[str, list[list[float | None]]] = {
        name: [[] for _ in creation] for name, creation in chunks.items()
    }
    for run_index in range(1, baseline.M + 1):
        run_rewrites: dict[str, list[ChunkRewrite]] = {}
        for name, creation in chunks.items():
            rewrites = _rewrite(config, session, creation, baseline.profiles[run_index], run_index)
            run_rewrites[name] = rewrites
            deltas = to_chunk_deltas(rewrites, session.distance)
            per_run[name].append(aggregate_run(name, run_index, deltas))
            for delta, rewrite in zip(deltas, rewrites, strict=True):
                by_chunk[name][delta.chunk_index].append(delta.delta if rewrite.ok else None)
        _write_rewrites(session.run_dir, run_index, run_rewrites)
        _write_deltas(session.run_dir, run_index, run_rewrites, session.distance)

    scores = {
        name: aggregate_creation(
            name,
            runs,
            std_ddof=config.aggregate.std_ddof,
            max_failed_fraction=config.rewrite.max_failed_fraction,
        )
        for name, runs in per_run.items()
    }
    return scores, by_chunk


def _finish(config: Config, session: _Session, result: CheckResult, summary: str) -> CheckResult:
    """Write the result, the table behind it, the summary and the manifest that closes the run."""
    _dump(session.run_dir / f"{result.check}.json", result.to_dict())
    if result.rows:
        _write_table(session.run_dir / f"{result.check}.csv", result.rows)
    (session.run_dir / "summary.md").write_text(summary, encoding="utf-8", newline="\n")

    calls: dict[str, Any] = {}
    if (session.run_dir / "calls.jsonl").is_file():
        calls = asdict(summarize(read_ledger(session.run_dir / "calls.jsonl")))
    manifest = {
        "run_id": session.run_id,
        "experiment": result.check,
        "baseline": result.baseline,
        "started_utc": session.started.isoformat(),
        "ended_utc": datetime.now(UTC).isoformat(),
        "config_hash": config.config_hash(),
        "seed": config.run.seed,
        "provider": config.llm.provider,
        "model_id": getattr(session.provider, "model_id", None)
        or config.llm.model_id
        or default_model(config.llm.provider),
        **session.code,
        "verdict": result.verdict,
        "calls": calls,
    }
    _dump(session.run_dir / "manifest.json", manifest)
    logger.info(
        "validation.complete", check=result.check, run_id=session.run_id, verdict=result.verdict
    )
    return result


def _write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    """A per-item table; an empty cell is a value that does not exist."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if value is None else value for key, value in row.items()})


def render_summary(result: CheckResult, title: str, notes: Sequence[str]) -> str:
    """A check's written result, as markdown."""
    return "\n".join(
        [
            f"# {title} (M14)",
            "",
            f"Run `{result.run_id}`, against baseline `{result.baseline}`. "
            "`docs/SPEC.md` section 7.",
            "",
            f"**Verdict: {result.verdict}.** {result.reason}",
            "",
            "| | |",
            "|---|---|",
            f"| measured | {result.measured} |",
            f"| passes if | {result.condition} |",
            "",
            *notes,
            "",
        ]
    )


# ----------------------------------------------------------------------------------- calibration


def coefficient_of_variation(values: Sequence[float]) -> float | None:
    """Sample standard deviation over the mean. Zero when every value is zero; None below 2 values."""
    if len(values) < 2:
        return None
    mean = statistics.fmean(values)
    spread = statistics.stdev(values)
    if mean == 0:
        return 0.0 if spread == 0 else None
    return spread / mean


def calibration_verdict(
    cvs: Sequence[float | None], max_cv: float, min_share: float
) -> tuple[str, int, int, float | None]:
    """The verdict over the measured chunks: ``(verdict, stable, measured, share)``."""
    measured = [cv for cv in cvs if cv is not None]
    if not measured:
        return UNDEFINED, 0, 0, None
    stable = sum(1 for cv in measured if cv <= max_cv)
    share = stable / len(measured)
    return (PASS if share >= min_share else FAIL), stable, len(measured), share


def run_calibration(config: Config, baseline_id: str, *, progress: bool = True) -> CheckResult:
    """Rewrite a sample of chunks ``repeats`` times under one profile and measure the spread.

    Repeat ``r`` is issued as replicate ``r`` of the baseline's run 1 request, so repeat 1 is the
    baseline's own answer and the others are new calls of the same prompt.
    """
    baseline = load_baseline(config, baseline_id)
    calibration = config.experiment.calibration
    chunks = _chunk(_load_texts(config), config)
    sample = select_control_sample(chunks, calibration.sample_chunks, config.run.seed)

    session = _open(config, "calibration", calls=True, progress=progress)
    by_creation: dict[str, list[Chunk]] = {}
    for chunk in sample:
        by_creation.setdefault(chunk.creation_id, []).append(chunk)
    _write_chunks(session.run_dir, by_creation)

    deltas: list[list[float]] = [[] for _ in sample]
    for repeat in range(1, calibration.repeats + 1):
        rewrites = _rewrite(config, session, sample, baseline.profiles[1], repeat)
        repeat_deltas: list[float | None] = []
        for position, rewrite in enumerate(rewrites):
            value = (
                session.distance(rewrite.original, rewrite.rewrite).value if rewrite.ok else None
            )
            repeat_deltas.append(value)
            if value is not None:
                deltas[position].append(value)
        _write_repeat(
            session.run_dir / "rewrites" / f"repeat_{repeat}.jsonl", rewrites, repeat_deltas
        )

    rows: list[dict[str, Any]] = []
    cvs: list[float | None] = []
    for chunk, values in zip(sample, deltas, strict=True):
        cv = coefficient_of_variation(values)
        cvs.append(cv)
        rows.append(
            {
                "creation_id": chunk.creation_id,
                "chunk_index": chunk.index,
                "n_valid": len(values),
                "mean_delta": statistics.fmean(values) if values else None,
                "sd_delta": statistics.stdev(values) if len(values) > 1 else None,
                "cv": cv,
                "stable": None if cv is None else cv <= calibration.max_cv,
                "deltas": ";".join(f"{value:.6f}" for value in values),
            }
        )

    verdict, stable, measured, share = calibration_verdict(
        cvs, calibration.max_cv, calibration.min_stable_share
    )
    measured_cvs = [cv for cv in cvs if cv is not None]
    if verdict == UNDEFINED:
        reason = "No chunk had two valid rewrites, so no spread could be measured."
    elif verdict == PASS:
        reason = "The deltas are stable across repeats on the large majority of chunks."
    else:
        reason = (
            "Too many chunks vary across repeats. The spec's remedy is to raise run.M and repeat "
            "(docs/SPEC.md section 7)."
        )
    result = CheckResult(
        check="calibration",
        run_id=session.run_id,
        run_dir=session.run_dir,
        baseline=baseline.run_id,
        verdict=verdict,
        measured=(
            f"{stable} of {measured} chunks ({share:.1%}) have CV <= {calibration.max_cv}"
            if share is not None
            else "no chunk measured"
        ),
        condition=f"at least {calibration.min_stable_share:.0%} of chunks have CV <= "
        f"{calibration.max_cv}",
        reason=reason,
        details={
            "n_sample": len(sample),
            "n_measured": measured,
            "n_stable": stable,
            "stable_share": share,
            "repeats": calibration.repeats,
            "max_cv": calibration.max_cv,
            "min_stable_share": calibration.min_stable_share,
            "median_cv": statistics.median(measured_cvs) if measured_cvs else None,
            "max_observed_cv": max(measured_cvs) if measured_cvs else None,
        },
        rows=rows,
    )
    return _finish(
        config,
        session,
        result,
        render_summary(
            result,
            "Calibration",
            [
                "Each sampled chunk was rewritten under the baseline's run 1 profile, all else",
                "constant. `calibration.csv` holds every chunk's deltas and CV, and",
                "`rewrites/repeat_<r>.jsonl` the texts. Repeat 1 is the baseline's own answer, from",
                "the cache.",
            ],
        ),
    )


def _write_repeat(path: Path, rewrites: list[ChunkRewrite], deltas: list[float | None]) -> None:
    """One repeat's rewrites, each with its chunk and delta, so a CV traces to its texts (R7)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "creation_id": rewrite.creation_id,
                "chunk_index": rewrite.chunk_index,
                "status": str(rewrite.status),
                "reason": str(rewrite.reason) if rewrite.reason else "",
                "attempts": rewrite.attempts,
                "delta": delta,
                "rewrite": rewrite.rewrite,
            },
            ensure_ascii=False,
        )
        for rewrite, delta in zip(rewrites, deltas, strict=True)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


# -------------------------------------------------------------------------------------- mixture


@dataclass(frozen=True)
class Splice:
    """Where a foreign passage was placed, in words and in chunks."""

    creation_id: str
    target: str
    source: str
    start: int
    n_words: int
    source_start: int
    first_chunk: int
    last_chunk: int


def splice_text(
    target: str,
    source: str,
    n_words: int,
    rng: random.Random,
    chunk_size: int,
    *,
    target_id: str = "",
    source_id: str = "",
) -> tuple[str, Splice]:
    """Replace ``n_words`` consecutive words of ``target`` with as many from ``source``.

    Both positions are drawn from ``rng`` (R8). The text keeps its length, so every chunk the splice
    does not touch is word for word the target's own.
    """
    words, foreign = split_words(target), split_words(source)
    if n_words >= len(words):
        raise CheckError(
            f"splice of {n_words} words does not fit in '{target_id}', which has {len(words)}"
        )
    if n_words > len(foreign):
        raise CheckError(f"mixture source '{source_id}' has only {len(foreign)} words")
    start = rng.randrange(0, len(words) - n_words + 1)
    source_start = rng.randrange(0, len(foreign) - n_words + 1)
    spliced = (
        words[:start] + foreign[source_start : source_start + n_words] + words[start + n_words :]
    )
    record = Splice(
        creation_id=f"{target_id}__{source_id}",
        target=target_id,
        source=source_id,
        start=start,
        n_words=n_words,
        source_start=source_start,
        first_chunk=start // chunk_size,
        last_chunk=(start + n_words - 1) // chunk_size,
    )
    return " ".join(spliced), record


def mean_by_chunk(by_chunk: list[list[float | None]]) -> list[float | None]:
    """Each chunk's delta averaged over the runs in which it was measured."""
    means: list[float | None] = []
    for values in by_chunk:
        valid = [value for value in values if value is not None]
        means.append(statistics.fmean(valid) if valid else None)
    return means


def peak_chunk(means: Sequence[float | None]) -> int | None:
    """The chunk with the highest mean delta; the first such chunk on a tie."""
    best: int | None = None
    best_value = 0.0
    for index, value in enumerate(means):
        if value is not None and (best is None or value > best_value):
            best, best_value = index, value
    return best


def choose_targets(baseline: Baseline, configured: list[str] | None, n: int) -> list[str]:
    """The creations to splice into: as configured, or the ``n`` most clearly authentic.

    Most clearly authentic means labelled authentic, not borderline, and lowest scoring: the texts
    the baseline is surest of, so that a flag after splicing is the splice's doing.
    """
    if configured:
        unknown = [name for name in configured if name not in baseline.scores]
        if unknown:
            raise CheckError(f"experiment.mixture.targets are not in the baseline: {unknown}")
        return list(configured)
    candidates = sorted(
        (
            (score, name)
            for name, score in baseline.scores.items()
            if score is not None
            and baseline.labels.get(name) == AUTHENTIC
            and name not in baseline.borderline
        ),
    )
    if not candidates:
        raise CheckError(
            "the baseline labels no creation clearly authentic, so none can be spliced"
        )
    return [name for _, name in candidates[:n]]


def run_mixture(config: Config, baseline_id: str, *, progress: bool = True) -> CheckResult:
    """Splice foreign passages into authentic creations and see whether the pipeline finds them."""
    baseline = load_baseline(config, baseline_id)
    mixture = config.experiment.mixture
    sources = load_sources(config.path(config.corpus.sources))
    foreign = sorted(sources.sets.get("mixture_sources", []), key=lambda source: source.id)
    if not foreign:
        raise CheckError("the sources file declares no mixture_sources")

    texts = _load_texts(config)
    targets = choose_targets(baseline, mixture.targets, mixture.n_splices)
    rng = random.Random(config.run.seed)
    directories = directories_from_config(config)

    spliced: dict[str, str] = {}
    splices: list[Splice] = []
    for position, target in enumerate(targets):
        source = foreign[position % len(foreign)]
        text, record = splice_text(
            texts[target],
            load_text(source, config.root, directories),
            mixture.splice_words,
            rng,
            config.chunking.P,
            target_id=target,
            source_id=source.id,
        )
        spliced[record.creation_id] = text
        splices.append(record)

    session = _open(config, "mixture", calls=True, progress=progress)
    _dump(session.run_dir / "splices.json", [asdict(record) for record in splices])
    chunks = {
        name: chunk_text(text, config.chunking.P, creation_id=name)
        for name, text in spliced.items()
    }
    _write_chunks(session.run_dir, chunks)
    scores, by_chunk = score_under_baseline(config, session, baseline, chunks)

    rows: list[dict[str, Any]] = []
    chunk_rows: list[dict[str, Any]] = []
    for record in splices:
        means = mean_by_chunk(by_chunk[record.creation_id])
        peak = peak_chunk(means)
        score = scores[record.creation_id].score
        label, borderline = label_for(score, baseline.tau, config.classify.borderline_band)
        tolerance = mixture.tolerance_chunks
        located = peak is not None and (
            record.first_chunk - tolerance <= peak <= record.last_chunk + tolerance
        )
        rows.append(
            {
                "creation_id": record.creation_id,
                "target": record.target,
                "source": record.source,
                "score_before": baseline.scores.get(record.target),
                "score_after": score,
                "tau": baseline.tau,
                "label": label,
                "borderline": borderline,
                "flagged": label == SUSPICIOUS,
                "splice_chunks": f"{record.first_chunk}-{record.last_chunk}",
                "peak_chunk": peak,
                "peak_located": located,
                "passed": label == SUSPICIOUS and located,
            }
        )
        for index, value in enumerate(means):
            chunk_rows.append(
                {
                    "creation_id": record.creation_id,
                    "chunk_index": index,
                    "in_splice": record.first_chunk <= index <= record.last_chunk,
                    "mean_delta": value,
                }
            )
    _write_table(session.run_dir / "mixture_chunks.csv", chunk_rows)

    flagged = sum(1 for row in rows if row["flagged"])
    located_count = sum(1 for row in rows if row["peak_located"])
    passed = all(row["passed"] for row in rows)
    result = CheckResult(
        check="mixture",
        run_id=session.run_id,
        run_dir=session.run_dir,
        baseline=baseline.run_id,
        verdict=PASS if passed else FAIL,
        measured=(
            f"{flagged} of {len(rows)} spliced creations above tau = {baseline.tau:.4f}; "
            f"delta peak at the splice in {located_count} of {len(rows)}"
        ),
        condition=(
            "every spliced creation is above tau, and its per-chunk delta peaks within "
            f"{mixture.tolerance_chunks} chunk(s) of the splice"
        ),
        reason=(
            "The pipeline flagged every splice and located it."
            if passed
            else "At least one splice was missed or not located; see mixture.csv."
        ),
        details={
            "n_spliced": len(rows),
            "n_flagged": flagged,
            "n_located": located_count,
            "splice_words": mixture.splice_words,
            "tolerance_chunks": mixture.tolerance_chunks,
            "tau": baseline.tau,
            "splices": [asdict(record) for record in splices],
        },
        rows=rows,
    )
    return _finish(
        config,
        session,
        result,
        render_summary(
            result,
            "Synthetic mixture",
            [
                "Each spliced creation is an authentic creation of the baseline with one passage",
                "of a mixture source in place of as many of its own words. It is scored under the",
                "baseline's profiles against the baseline's tau and is never part of either.",
                "`mixture.csv` has one row per spliced creation, `mixture_chunks.csv` every chunk's",
                "mean delta, and `splices.json` where each passage went.",
            ],
        ),
    )


# -------------------------------------------------------------------------------------- held-out


def run_heldout(config: Config, baseline_id: str, *, progress: bool = True) -> CheckResult:
    """Score the reserved texts under the baseline and compare each label with the expected one."""
    baseline = load_baseline(config, baseline_id)
    sources = load_sources(config.path(config.corpus.sources))
    reserved = sources.sets.get("heldout", [])
    if not reserved:
        raise CheckError("the sources file declares no heldout texts")
    missing = [
        source.id for source in reserved if source.expected_label not in (AUTHENTIC, SUSPICIOUS)
    ]
    if missing:
        raise CheckError(f"held-out texts without an expected_label: {', '.join(missing)}")

    directories = directories_from_config(config)
    chunks = {
        source.id: chunk_text(
            load_text(source, config.root, directories), config.chunking.P, creation_id=source.id
        )
        for source in reserved
    }
    session = _open(config, "heldout", calls=True, progress=progress)
    _write_chunks(session.run_dir, chunks)
    scores, _ = score_under_baseline(config, session, baseline, chunks)

    rows: list[dict[str, Any]] = []
    for source in reserved:
        score = scores[source.id].score
        label, borderline = label_for(score, baseline.tau, config.classify.borderline_band)
        rows.append(
            {
                "creation_id": source.id,
                "title": source.title,
                "expected": source.expected_label,
                "score": score,
                "tau": baseline.tau,
                "label": label,
                "borderline": borderline,
                "unreliable": scores[source.id].unreliable,
                "correct": label == source.expected_label,
            }
        )
    correct = sum(1 for row in rows if row["correct"])
    result = CheckResult(
        check="heldout",
        run_id=session.run_id,
        run_dir=session.run_dir,
        baseline=baseline.run_id,
        verdict=PASS if correct == len(rows) else FAIL,
        measured=f"{correct} of {len(rows)} held-out texts classified as expected",
        condition="every held-out text is classified as its expected_label",
        reason=(
            "The pipeline generalizes to the reserved texts."
            if correct == len(rows)
            else "At least one reserved text was misclassified; see heldout.csv."
        ),
        details={
            "n_texts": len(rows),
            "n_correct": correct,
            "n_borderline": sum(1 for row in rows if row["borderline"]),
            "tau": baseline.tau,
        },
        rows=rows,
    )
    return _finish(
        config,
        session,
        result,
        render_summary(
            result,
            "Held-out generalization",
            [
                "The reserved texts were scored under the baseline's profiles against its tau,",
                "chunk by chunk and run by run as a creation is. They were reserved before the",
                "pipeline was finalized (docs/DATA.md section 1.1) and never shape a profile.",
            ],
        ),
    )


# ----------------------------------------------------------------------------- noise robustness


def compare_labels(
    with_noise: dict[str, str],
    without_noise: dict[str, str],
    borderline: set[str] | frozenset[str],
) -> tuple[list[str], list[str], list[str]]:
    """Creations compared, those whose label changed, and those left out as borderline."""
    shared = sorted(with_noise.keys() & without_noise.keys())
    skipped = [name for name in shared if name in borderline]
    compared = [name for name in shared if name not in borderline]
    changed = [name for name in compared if with_noise[name] != without_noise[name]]
    return compared, changed, skipped


def run_noise(config: Config, with_id: str, without_id: str) -> CheckResult:
    """Compare a run with noise injection against the same run without it. No calls."""
    with_dir, without_dir = _finished_run(config, with_id), _finished_run(config, without_id)
    with_snapshot, without_snapshot = _read_snapshot(with_dir), _read_snapshot(without_dir)
    if not with_snapshot.get("noise", {}).get("enabled"):
        raise CheckError(f"'{with_id}' ran without noise injection; it must be the run with noise")
    if without_snapshot.get("noise", {}).get("enabled"):
        raise CheckError(f"'{without_id}' ran with noise injection; it must be the run without")
    differing = method_differences(with_snapshot, without_snapshot, also_free=("noise",))
    if differing:
        raise CheckError(
            f"the two runs differ in more than noise injection: {', '.join(differing)}. Run the "
            "variant with the same configuration and --set noise.enabled=false."
        )

    with_scores, with_labels, with_borderline = _read_scores(with_dir)
    without_scores, without_labels, without_borderline = _read_scores(without_dir)
    if with_labels.keys() != without_labels.keys():
        raise CheckError(
            "the two runs scored different creations, so their labels cannot be compared"
        )
    compared, changed, skipped = compare_labels(
        with_labels, without_labels, with_borderline | without_borderline
    )

    session = _open(config, "noise", calls=False)
    rows = [
        {
            "creation_id": name,
            "score_with_noise": with_scores[name],
            "score_without_noise": without_scores[name],
            "label_with_noise": with_labels[name],
            "label_without_noise": without_labels[name],
            "borderline": name in skipped,
            "changed": name in changed,
        }
        for name in sorted(with_labels)
    ]
    first: list[float] = []
    second: list[float] = []
    for name in sorted(with_labels):
        a, b = with_scores[name], without_scores[name]
        if a is not None and b is not None:
            first.append(a)
            second.append(b)
    correlation: float | None = None
    if len(first) >= 2:
        try:
            correlation = statistics.correlation(first, second)
        except statistics.StatisticsError:  # a constant series has no correlation
            correlation = None
    taus = {
        name: json.loads((directory / "threshold.json").read_text(encoding="utf-8"))["tau"]
        for name, directory in (("with_noise", with_dir), ("without_noise", without_dir))
    }

    verdict = UNDEFINED if not compared else (PASS if not changed else FAIL)
    result = CheckResult(
        check="noise",
        run_id=session.run_id,
        run_dir=session.run_dir,
        baseline=with_id,
        verdict=verdict,
        measured=(
            f"{len(changed)} of {len(compared)} non-borderline creations changed label "
            f"({len(skipped)} borderline left out)"
        ),
        condition="no non-borderline creation changes label between the two variants",
        reason=(
            "No creation was comparable: every one is borderline in a run."
            if verdict == UNDEFINED
            else "Authentic labels are stable under noise injection."
            if verdict == PASS
            else f"Labels changed: {', '.join(changed)}."
        ),
        details={
            "with_noise": with_id,
            "without_noise": without_id,
            "n_compared": len(compared),
            "n_changed": len(changed),
            "changed": changed,
            "n_borderline": len(skipped),
            "tau": taus,
            "score_correlation": correlation,
            "suspicious_with_noise": sorted(
                name for name, label in with_labels.items() if label == SUSPICIOUS
            ),
            "suspicious_without_noise": sorted(
                name for name, label in without_labels.items() if label == SUSPICIOUS
            ),
        },
        rows=rows,
    )
    return _finish(
        config,
        session,
        result,
        render_summary(
            result,
            "Noise robustness",
            [
                f"With noise: `{with_id}`. Without: `{without_id}`. A creation borderline in either",
                "run is left out of the comparison and listed in `noise.csv`, as docs/TESTING.md",
                "section 5 specifies. The Pearson correlation of the two runs' scores is in",
                "`noise.json`.",
            ],
        ),
    )


# -------------------------------------------------------------------------------------- the plan


@dataclass(frozen=True)
class CheckPlan:
    """What a check would send, before anything is sent."""

    check: str
    n_texts: int
    n_chunks: int
    rewrite_calls: int


def plan_check(config: Config, check: str, baseline_id: str) -> CheckPlan:
    """Count a check's first-attempt rewrite calls. Calls the baseline already made are cached."""
    baseline = load_baseline(config, baseline_id)
    if check == "calibration":
        calibration = config.experiment.calibration
        sample = select_control_sample(
            _chunk(_load_texts(config), config), calibration.sample_chunks, config.run.seed
        )
        n_texts = len({chunk.creation_id for chunk in sample})
        return CheckPlan(check, n_texts, len(sample), len(sample) * calibration.repeats)
    sources = load_sources(config.path(config.corpus.sources))
    directories = directories_from_config(config)
    if check == "heldout":
        reserved = sources.sets.get("heldout", [])
        n_chunks = sum(
            len(chunk_text(load_text(source, config.root, directories), config.chunking.P))
            for source in reserved
        )
        return CheckPlan(check, len(reserved), n_chunks, n_chunks * baseline.M)
    if check == "mixture":
        mixture = config.experiment.mixture
        targets = choose_targets(baseline, mixture.targets, mixture.n_splices)
        texts = _load_texts(config)
        n_chunks = sum(len(chunk_text(texts[name], config.chunking.P)) for name in targets)
        # Only the chunks a splice touches are new; at most this many per splice.
        touched = -(-mixture.splice_words // config.chunking.P) + 1
        return CheckPlan(check, len(targets), n_chunks, len(targets) * touched * baseline.M)
    raise CheckError(f"no plan for '{check}'; choose one of calibration, mixture, heldout")


__all__ = [
    "CHECKS",
    "Baseline",
    "CheckError",
    "CheckPlan",
    "CheckResult",
    "Splice",
    "calibration_verdict",
    "choose_targets",
    "coefficient_of_variation",
    "compare_labels",
    "label_for",
    "load_baseline",
    "mean_by_chunk",
    "method_differences",
    "peak_chunk",
    "plan_check",
    "render_summary",
    "run_calibration",
    "run_heldout",
    "run_mixture",
    "run_noise",
    "score_under_baseline",
    "splice_text",
]
