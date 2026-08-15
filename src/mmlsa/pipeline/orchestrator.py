"""The `M`-run loop, and the run directory that records what it did.

This is the module that turns six steps into one command. Everything before it was a component;
this is the pipeline.

Two ideas govern the shape of it.

**A run directory is immutable** (R9). It is named for the configuration and the seed that produced
it, and a completed one is never written to again. The classic failure this avoids is silently
overwriting the result you are about to report, which is undetectable afterwards because there is
nothing left to compare against.

**Chunking happens once, not once per run.** Steps 2 and 4 contain no model call and no randomness,
so the chunks of a creation are the same in every run. What varies across runs is the profile, and
therefore the rewrite, and therefore the delta. Re-chunking per run would be harmless but would
imply a dependence that does not exist.

See ``docs/ARCHITECTURE.md`` section 6 for the artifact layout.
"""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from mmlsa import __version__
from mmlsa.chunking import Chunk, chunk_text
from mmlsa.config import Config
from mmlsa.corpus.loader import (
    directories_from_config,
    load_corpus,
    load_sources,
    load_text,
)
from mmlsa.distance.registry import build_distance
from mmlsa.distance.tokenize import load_function_words
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger, read_ledger, summarize
from mmlsa.llm.providers import build_provider, declared_context_window
from mmlsa.llm.runner import Runner
from mmlsa.pipeline.classify import classify, compute_threshold
from mmlsa.pipeline.noise import NoiseAssignment, select_noise
from mmlsa.pipeline.profile import ProfileResult, extract_profile, plan_packing
from mmlsa.pipeline.rewrite import (
    ChunkRewrite,
    ValidationConfig,
    report_creation,
    rewrite_chunks,
    to_chunk_deltas,
)
from mmlsa.pipeline.score import CreationScore, aggregate_creation, aggregate_run, scorable_scores
from mmlsa.reporting import plots
from mmlsa.reporting.tables import scores_frame, write_scores_csv, write_threshold_json
from mmlsa.utils.logging import configure_logging, get_logger
from mmlsa.utils.tokens import estimate_tokens

logger = get_logger(__name__)


class RunError(Exception):
    """Raised when a run cannot start, or would overwrite a completed one."""


@dataclass
class DryRunPlan:
    """What a run would do, computed without issuing a single request."""

    run_id: str
    n_creations: int
    n_chunks: int
    n_runs: int
    profile_calls: int
    rewrite_calls: int
    noise_creations: list[str]
    estimated_input_tokens: int
    cached_calls: int = 0

    @property
    def total_calls(self) -> int:
        """Every call the run would make, cached or not."""
        return self.profile_calls + self.rewrite_calls

    @property
    def calls_to_issue(self) -> int:
        """Calls that would actually reach the provider."""
        return max(0, self.total_calls - self.cached_calls)


@dataclass
class RunResult:
    """Everything a completed run produced."""

    run_id: str
    run_dir: Path
    creations: list[CreationScore]
    threshold: Any
    classification: Any
    noise_scores: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------------------------ run identity


def build_run_id(config: Config, *, timestamp: datetime | None = None, tag: str = "") -> str:
    """``<UTC date>T<HHMM>-<config hash>-s<seed>``, plus the configured tag.

    The configuration hash is in the name because a run's identity is its inputs. Two runs with
    different parameters cannot collide, and two runs with the same parameters are distinguished by
    when they were started.
    """
    stamp = (timestamp or datetime.now(UTC)).strftime("%Y%m%dT%H%M")
    label = tag or config.run.tag
    suffix = f"-{label}" if label else ""
    return f"{stamp}-{config.config_hash()[:8]}-s{config.run.seed}{suffix}"


def _git_commit(root: Path) -> str:
    """The commit a run was produced from, when the working tree is a repository."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def is_complete(run_dir: Path) -> bool:
    """Whether a run directory holds a finished run.

    A run is finished when its manifest records an end time. A directory without one is an
    interrupted run and may be resumed; a directory with one is a result and is never touched again.
    """
    manifest = run_dir / "manifest.json"
    if not manifest.is_file():
        return False
    try:
        return bool(json.loads(manifest.read_text(encoding="utf-8")).get("ended_utc"))
    except (OSError, json.JSONDecodeError):
        return False


# ---------------------------------------------------------------------------------------- planning


def plan_run(
    config: Config,
    *,
    run_id: str = "",
    context_window: int | None = None,
) -> DryRunPlan:
    """Enumerate the whole run without touching a provider.

    Run this before anything wide. It reports the exact number of calls and an input-token estimate.

    The window is taken from the configured model's declared capabilities, which needs no
    credentials, and falls back to a nominal one million for the offline providers, which have no
    fixed window to declare. It affects only the profile-call count; the rewrite count, which
    dominates, does not depend on it.
    """
    window = (
        context_window
        or declared_context_window(config.llm.provider, config.llm.model_id)
        or 1_000_000
    )
    sources = load_sources(config.path(config.corpus.sources))
    directories = directories_from_config(config)
    texts = load_corpus(
        sources,
        config.root,
        include_ids=config.corpus.include_ids,
        exclude_ids=config.corpus.exclude_ids,
        directories=directories,
    )

    noise = select_noise(
        [source.id for source in sources.sets.get("noise_pool", [])],
        config.run.M,
        config.run.seed,
        enabled=config.noise.enabled,
        first_run_plain=config.noise.first_run_plain,
    )

    chunks = {
        name: chunk_text(text, config.chunking.P, creation_id=name) for name, text in texts.items()
    }
    n_chunks = sum(len(c) for c in chunks.values())

    corpus_chunk_tokens = sum(
        estimate_tokens(chunk.text, config.profile.tokens_per_word)
        for creation in chunks.values()
        for chunk in creation
    )

    profile_calls = 0
    rewrite_calls = 0
    estimated_tokens = 0

    for run_index in range(1, config.run.M + 1):
        corpus = dict(texts)
        noise_id = noise.for_run(run_index)

        if noise_id:
            noise_text = load_text(sources.by_id(noise_id), config.root, directories)
            corpus[noise_id] = noise_text
            if config.noise.score_injected_text:
                noise_chunks = chunk_text(noise_text, config.chunking.P, creation_id=noise_id)
                rewrite_calls += len(noise_chunks)
                estimated_tokens += sum(
                    estimate_tokens(c.text, config.profile.tokens_per_word) for c in noise_chunks
                )

        bins = plan_packing(
            corpus,
            context_window=window,
            budget_tokens=config.profile.context_budget_tokens,
            tokens_per_word=config.profile.tokens_per_word,
        )
        merged = 1 if len(bins) > 1 and config.profile.merge_when_multiple else 0
        profile_calls += len(bins) + merged

        # Step 1 sends the whole corpus once per run; Step 3 sends every chunk once per run.
        estimated_tokens += sum(b.tokens for b in bins)
        rewrite_calls += n_chunks
        estimated_tokens += corpus_chunk_tokens

    return DryRunPlan(
        run_id=run_id or build_run_id(config),
        n_creations=len(texts),
        n_chunks=n_chunks,
        n_runs=config.run.M,
        profile_calls=profile_calls,
        rewrite_calls=rewrite_calls,
        noise_creations=noise.injected,
        estimated_input_tokens=estimated_tokens,
    )


# ----------------------------------------------------------------------------------- the run loop


def execute_run(config: Config, *, run_id: str = "", progress: bool = True) -> RunResult:
    """Run the whole pipeline and write an immutable run directory.

    The loop is: for each of the `M` runs, assemble that run's corpus (plain for run 1, plus one
    foreign creation thereafter), extract a profile from it, rewrite every chunk of every creation
    under that profile, and measure. Then average across runs, threshold, and classify.

    The injected creation is scored alongside the rest but is held out of the threshold and out of
    the reported set. It is free evidence: a foreign text should land above `tau`, and if it does not,
    something is wrong that the corpus alone would not reveal.
    """
    run_id = run_id or build_run_id(config)
    run_dir = config.path(config.run.out_dir) / run_id

    if is_complete(run_dir):
        raise RunError(
            f"run '{run_id}' is already complete at {run_dir}. Run artifacts are immutable; change "
            "a parameter to get a new run id, or delete the directory deliberately."
        )

    run_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(log_file=run_dir / "logs" / "run.log")

    started = datetime.now(UTC)
    (run_dir / "config.snapshot.yaml").write_text(
        yaml.safe_dump(config.to_dict(), sort_keys=True), encoding="utf-8", newline="\n"
    )

    sources = load_sources(config.path(config.corpus.sources))
    directories = directories_from_config(config)
    texts = load_corpus(
        sources,
        config.root,
        include_ids=config.corpus.include_ids,
        exclude_ids=config.corpus.exclude_ids,
        directories=directories,
    )
    titles = {source.id: source.title for source in sources.all_texts()}

    noise = select_noise(
        [source.id for source in sources.sets.get("noise_pool", [])],
        config.run.M,
        config.run.seed,
        enabled=config.noise.enabled,
        first_run_plain=config.noise.first_run_plain,
    )

    function_words_path = str(config.path(config.distance.function_words))
    function_words = frozenset(load_function_words(function_words_path))
    distance = build_distance(config.distance.metric, function_words_path)

    cache = ResponseCache(config.path(config.llm.cache_dir), mode=config.llm.mode)
    provider = build_provider(
        config.llm.provider,
        model_id=config.llm.model_id,
        cache=cache,
        timeout_seconds=config.llm.timeout_seconds,
    )
    runner = Runner(
        provider=provider,
        cache=cache,
        ledger=Ledger(run_dir / "calls.jsonl", run_id=run_id),
        concurrency=config.llm.concurrency,
        requests_per_minute=config.llm.requests_per_minute,
        tokens_per_minute=config.llm.tokens_per_minute,
        max_transient_retries=config.llm.max_transient_retries,
        mode=config.llm.mode,
        progress=progress,
    )

    # Step 2, once. Chunks do not depend on the run.
    chunks = {
        name: chunk_text(text, config.chunking.P, creation_id=name) for name, text in texts.items()
    }
    _write_chunks(run_dir, chunks)

    validation = ValidationConfig(
        min_length_ratio=config.rewrite.validation.min_length_ratio,
        max_length_ratio=config.rewrite.validation.max_length_ratio,
        min_content_retention=config.rewrite.validation.min_content_retention,
        strip_preamble=config.rewrite.validation.strip_preamble,
        strip_code_fences=config.rewrite.validation.strip_code_fences,
    )

    per_run: dict[str, list] = {name: [] for name in texts}
    noise_scores: list[dict[str, Any]] = []
    reports: list[Any] = []

    for run_index in range(1, config.run.M + 1):
        corpus = dict(texts)
        noise_id = noise.for_run(run_index)
        noise_chunks: list[Chunk] = []

        if noise_id:
            noise_text = load_text(sources.by_id(noise_id), config.root, directories)
            corpus[noise_id] = noise_text
            noise_chunks = chunk_text(noise_text, config.chunking.P, creation_id=noise_id)
            # Recorded alongside the corpus chunks: the noise diagnostic is a number in the report,
            # and R7 requires it to trace back to the text behind it just like any other score.
            _write_chunks(run_dir, {noise_id: noise_chunks})
            logger.info("run.noise_injected", run_index=run_index, creation_id=noise_id)

        # Step 1, on this run's corpus, noise included.
        profile = extract_profile(
            corpus,
            runner,
            run_index=run_index,
            structured=config.profile.structured_output,
            budget_tokens=config.profile.context_budget_tokens,
            tokens_per_word=config.profile.tokens_per_word,
            context_fraction=0.70,
            merge_when_multiple=config.profile.merge_when_multiple,
            max_output_tokens=config.profile.max_output_tokens,
            temperature=config.llm.temperature,
            noise_creation_id=noise_id,
        )
        _write_profile(run_dir, profile)
        profile_text = profile.profile.render()

        run_rewrites: dict[str, list[ChunkRewrite]] = {}

        # Steps 3 to 5, for the classified corpus.
        for name, creation_chunks in chunks.items():
            rewrites = rewrite_chunks(
                creation_chunks,
                profile_text,
                runner,
                function_words,
                run_index=run_index,
                validation=validation,
                max_retries=config.rewrite.max_retries,
                max_output_tokens=config.rewrite.max_output_tokens,
                temperature=config.llm.temperature,
            )
            run_rewrites[name] = rewrites
            reports.append(
                report_creation(
                    name,
                    run_index,
                    rewrites,
                    max_failed_fraction=config.rewrite.max_failed_fraction,
                )
            )
            per_run[name].append(
                aggregate_run(name, run_index, to_chunk_deltas(rewrites, distance))
            )

        # The injected creation is scored as a diagnostic, never as a member of the corpus.
        if noise_id and config.noise.score_injected_text:
            noise_rewrites = rewrite_chunks(
                noise_chunks,
                profile_text,
                runner,
                function_words,
                run_index=run_index,
                validation=validation,
                max_retries=config.rewrite.max_retries,
                max_output_tokens=config.rewrite.max_output_tokens,
                temperature=config.llm.temperature,
            )
            run_rewrites[noise_id] = noise_rewrites
            score = aggregate_run(noise_id, run_index, to_chunk_deltas(noise_rewrites, distance))
            noise_scores.append(
                {
                    "creation_id": noise_id,
                    "title": titles.get(noise_id, ""),
                    "run_index": run_index,
                    "n_chunks": score.n_chunks_total,
                    "score": score.mean_delta,
                }
            )

        _write_rewrites(run_dir, run_index, run_rewrites)
        _write_deltas(run_dir, run_index, run_rewrites, distance)

    # Step 5 across runs, then Step 6. The noise never reaches this point.
    creations = [
        aggregate_creation(
            name,
            run_scores,
            std_ddof=config.aggregate.std_ddof,
            max_failed_fraction=config.rewrite.max_failed_fraction,
        )
        for name, run_scores in per_run.items()
    ]

    ids, scores = scorable_scores(creations)
    threshold = compute_threshold(
        scores,
        method=config.classify.method,
        cross_check_skimage=config.classify.cross_check_skimage,
        agreement_tol=config.classify.otsu_agreement_tol,
        min_separability=config.classify.bimodality_min_separability,
        min_gap_ratio=config.classify.bimodality_min_gap_ratio,
        manual_tau=config.classify.manual_tau,
        seed=config.run.seed,
    )
    classification = classify(
        ids, scores, threshold, borderline_band=config.classify.borderline_band
    )

    frame = scores_frame(creations, classification, titles=titles)
    write_scores_csv(frame, run_dir / "scores.csv")
    write_threshold_json(threshold, classification, run_dir / "threshold.json")
    _write_noise_diagnostics(run_dir, noise_scores, threshold.tau)

    if config.report.figures and len(scores) >= 2:
        plots.sorted_scatter(ids, scores, threshold, run_dir / "figures" / "sorted_scatter.png")
        plots.histogram(scores, threshold, run_dir / "figures" / "histogram.png")
        plots.run_variance(
            [c.creation_id for c in creations],
            [c.per_run for c in creations],
            run_dir / "figures" / "run_variance.png",
        )

    manifest = _build_manifest(
        config, run_id, started, provider, noise, reports, creations, threshold, run_dir
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    logger.info(
        "run.complete",
        run_id=run_id,
        n_creations=len(creations),
        suspicious=len(classification.suspicious),
        tau=threshold.tau,
        calls_live=runner.stats.live,
        calls_cached=runner.stats.cached,
    )

    return RunResult(
        run_id=run_id,
        run_dir=run_dir,
        creations=creations,
        threshold=threshold,
        classification=classification,
        noise_scores=noise_scores,
        manifest=manifest,
    )


# ------------------------------------------------------------------------------------- artifacts


def _write_chunks(run_dir: Path, chunks: dict[str, list[Chunk]]) -> None:
    """One JSON Lines file per creation, so a score traces to the exact text behind it (R7)."""
    directory = run_dir / "chunks"
    directory.mkdir(parents=True, exist_ok=True)
    for name, creation_chunks in chunks.items():
        lines = [
            json.dumps(
                {
                    "chunk_index": chunk.index,
                    "n_words": chunk.n_words,
                    "word_start": chunk.word_start,
                    "word_end": chunk.word_end,
                    "sha256": chunk.sha256,
                    "text": chunk.text,
                },
                ensure_ascii=False,
            )
            for chunk in creation_chunks
        ]
        (directory / f"{name}.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
        )


def _write_profile(run_dir: Path, profile: ProfileResult) -> None:
    """The merged profile, the partials and the packing, per run."""
    directory = run_dir / "profiles"
    directory.mkdir(parents=True, exist_ok=True)
    index = profile.run_index

    payload = profile.to_dict()
    _dump(directory / f"run_{index}_merged.json", payload["profile"])
    _dump(directory / f"run_{index}_partials.json", payload["partials"])
    _dump(directory / f"run_{index}_packing.json", payload["packing"])


def _write_rewrites(run_dir: Path, run_index: int, rewrites: dict[str, list[ChunkRewrite]]) -> None:
    """Every rewrite, per creation per run."""
    directory = run_dir / "rewrites" / f"run_{run_index}"
    directory.mkdir(parents=True, exist_ok=True)
    for name, creation_rewrites in rewrites.items():
        lines = [
            json.dumps(
                {
                    "chunk_index": rewrite.chunk_index,
                    "status": rewrite.status.value,
                    "attempts": rewrite.attempts,
                    "reason": rewrite.reason.value if rewrite.reason else "",
                    "n_words_original": rewrite.n_words_original,
                    "n_words_rewrite": rewrite.n_words_rewrite,
                    "rewrite": rewrite.rewrite,
                },
                ensure_ascii=False,
            )
            for rewrite in creation_rewrites
        ]
        (directory / f"{name}.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
        )


def _write_deltas(
    run_dir: Path,
    run_index: int,
    rewrites: dict[str, list[ChunkRewrite]],
    distance: Any,
) -> None:
    """Per-chunk deltas for one run, as CSV."""
    import csv

    directory = run_dir / "deltas"
    directory.mkdir(parents=True, exist_ok=True)

    with (directory / f"run_{run_index}.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["creation_id", "chunk_index", "delta", "n_fw_orig", "n_fw_rew", "status", "degenerate"]
        )
        for name in sorted(rewrites):
            for rewrite in rewrites[name]:
                if rewrite.ok:
                    result = distance(rewrite.original, rewrite.rewrite)
                    writer.writerow(
                        [
                            name,
                            rewrite.chunk_index,
                            f"{result.value:.6f}",
                            result.n_units_original,
                            result.n_units_rewrite,
                            "ok",
                            int(result.degenerate),
                        ]
                    )
                else:
                    reason = rewrite.reason.value if rewrite.reason else "unknown"
                    writer.writerow([name, rewrite.chunk_index, "", "", "", f"failed:{reason}", 0])


def _write_noise_diagnostics(run_dir: Path, noise_scores: list[dict[str, Any]], tau: float) -> None:
    """The injected creations and where they landed relative to the threshold.

    Always written, even when empty, so that a run with noise disabled says so rather than leaving a
    reader to wonder whether the file is missing or the feature was off.
    """
    import csv

    with (run_dir / "noise_diagnostics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["creation_id", "title", "run_index", "n_chunks", "score", "above_tau"])
        for entry in noise_scores:
            score = entry["score"]
            writer.writerow(
                [
                    entry["creation_id"],
                    entry["title"],
                    entry["run_index"],
                    entry["n_chunks"],
                    f"{score:.6f}" if score is not None else "",
                    int(score > tau) if score is not None else "",
                ]
            )


def _dump(path: Path, payload: Any) -> None:
    """Write JSON with stable formatting."""
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _build_manifest(
    config: Config,
    run_id: str,
    started: datetime,
    provider: Any,
    noise: NoiseAssignment,
    reports: list[Any],
    creations: list[CreationScore],
    threshold: Any,
    run_dir: Path,
) -> dict[str, Any]:
    """Everything needed to say what this run was and what it cost."""
    ledger = summarize(read_ledger(run_dir / "calls.jsonl"))
    unreliable = [report.creation_id for report in reports if report.unreliable]

    return {
        "run_id": run_id,
        "started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ended_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "package_version": __version__,
        "git_commit": _git_commit(config.root),
        "python": platform.python_version(),
        "config_hash": config.config_hash(),
        "seed": config.run.seed,
        "M": config.run.M,
        "P": config.chunking.P,
        "distance_metric": config.distance.metric,
        "classifier": config.classify.method,
        "provider": provider.name,
        "model_id": provider.model_id,
        "llm_mode": config.llm.mode,
        "noise": {
            "enabled": config.noise.enabled,
            "by_run": noise.by_run,
            "injected": noise.injected,
        },
        "counts": {
            "n_creations": len(creations),
            "n_scored": sum(1 for creation in creations if creation.scorable),
            "n_unreliable": len(set(unreliable)),
            "unreliable_creations": sorted(set(unreliable)),
            "n_chunks_failed": sum(report.n_failed for report in reports),
            "n_chunks_retried": sum(report.n_retried for report in reports),
        },
        "calls": {
            "total": ledger.total,
            "live": ledger.live,
            "cached": ledger.cached,
            "failed": ledger.failed,
            "by_tag": ledger.by_tag,
            "input_tokens": ledger.input_tokens,
            "output_tokens": ledger.output_tokens,
        },
        "threshold": {
            "tau": threshold.tau,
            "method": threshold.method,
            "flagged": threshold.flagged,
        },
    }
