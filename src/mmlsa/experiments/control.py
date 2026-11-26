"""Stage 5, the control experiment: Mode A against Mode B, paired by chunk (milestone M13).

The experiment that decides whether the method measures something or is riding on what the model
already knows about the author. Every sampled chunk is rewritten twice:

* **Mode A** under the profile Step 1 extracts from the configured corpus, exactly as in a run;
* **Mode B** under the generic prompt, which names the author (``corpus.author_label``) and gives no
  profile. It is the one prompt in the system that names anyone, and the name comes from
  configuration (R1, ``docs/PROMPTS.md`` section 5).

Both arms go through the same validation and the same retries, so they differ in the instruction and
in nothing else. Success metric 2 (``docs/SPEC.md`` section 6) asks that Mode A's delta be
significantly **lower**: the explicit profile should leave less to rewrite than a bare instruction.

**Pairing is by chunk.** A chunk enters the test only when both arms produced a valid rewrite of it;
the chunks left out are counted per arm and reported, never silently dropped.

**The statistics** (``docs/EXPERIMENTS.md`` Stage 5): a paired t-test on the per-chunk differences
``delta_A - delta_B``, the mean difference with its ``1 - alpha`` confidence interval, Cohen's ``d``
in its paired form ``d_z`` (the mean difference over the standard deviation of the differences), a
Wilcoxon signed-rank test as the non-parametric backup, and the achieved power of the t-test at the
observed effect. Which p-value decides the verdict, two-sided or one-sided, is not fixed by the spec;
``experiment.control.alternative`` holds the choice and both are reported (``docs/OPEN_QUESTIONS.md``
Q20).

The profile comes from the plain corpus, as in run 1 of a run: no noise is injected, because the
experiment compares prompts, not runs. Mode A's requests are then the same as run 1's in a run over
the same corpus and model, so where that run is in the cache, Mode A costs nothing.

The run's own helpers are reused (``_profile_options``, the profile source check, the artifact
writers), so the two cannot drift apart.
"""

from __future__ import annotations

import csv
import json
import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from scipy import stats as scipy_stats

from mmlsa.chunking import Chunk, chunk_text
from mmlsa.config import Config
from mmlsa.corpus.loader import directories_from_config, load_corpus, load_sources
from mmlsa.distance.registry import build_distance
from mmlsa.distance.tokenize import load_function_words
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger, read_ledger, summarize
from mmlsa.llm.providers import build_provider, declared_context_window, default_model
from mmlsa.llm.runner import Runner
from mmlsa.pipeline.orchestrator import (
    _check_profile_sources,
    _code_version,
    _dump,
    _profile_options,
    _write_chunks,
    _write_profile,
    build_run_id,
)
from mmlsa.pipeline.profile import ProfileResult, extract_profile, plan_packing
from mmlsa.pipeline.rewrite import (
    ChunkRewrite,
    ValidationConfig,
    rewrite_chunks,
    rewrite_chunks_generic,
)
from mmlsa.utils.logging import configure_logging, get_logger
from mmlsa.utils.tokens import estimate_tokens

logger = get_logger(__name__)

RUN_INDEX = 1
"""The control experiment is one run: its profile is run 1's, from the plain corpus."""


class ControlError(Exception):
    """Raised when the control experiment cannot be set up, or would overwrite a finished one."""


# ------------------------------------------------------------------------------------ the sample


def allocate(counts: dict[str, int], size: int) -> dict[str, int]:
    """How many chunks each creation contributes: proportional to its chunk count.

    Largest-remainder allocation: each creation gets the floor of its exact share, and the chunks
    still to place go to the largest fractional parts, ties broken by creation id. The total is
    exactly ``size`` (or every chunk, when ``size`` is not smaller than the corpus), and no creation
    is given more chunks than it has.
    """
    total = sum(counts.values())
    if size >= total:
        return dict(counts)

    shares = {name: size * count / total for name, count in counts.items()}
    allocation = {name: math.floor(share) for name, share in shares.items()}
    left = size - sum(allocation.values())
    by_remainder = sorted(counts, key=lambda name: (-(shares[name] - allocation[name]), name))
    for name in by_remainder[:left]:
        allocation[name] += 1
    return allocation


def select_control_sample(
    chunks: dict[str, list[Chunk]],
    size: int,
    seed: int,
    *,
    stratify: bool = True,
) -> list[Chunk]:
    """Draw the chunks both arms rewrite, in creation then chunk order.

    Stratified, the draw is proportional to each creation's chunk count (``docs/OPEN_QUESTIONS.md``
    Q8), so a long play is not under-represented and a short one does not crowd the sample. Flat, it
    is a simple random sample of every chunk. Either way it is deterministic in ``(chunks, size,
    seed)`` (R8): one ``random.Random(seed)`` draws within each creation in sorted order.
    """
    populated = {name: creation for name, creation in sorted(chunks.items()) if creation}
    if not populated:
        raise ControlError("the configured corpus produced no chunks to sample")

    rng = random.Random(seed)
    if stratify:
        allocation = allocate({name: len(creation) for name, creation in populated.items()}, size)
        drawn: list[Chunk] = []
        for name, creation in populated.items():
            drawn += rng.sample(creation, allocation[name])
    else:
        everything = [chunk for creation in populated.values() for chunk in creation]
        drawn = rng.sample(everything, min(size, len(everything)))

    return sorted(drawn, key=lambda chunk: (chunk.creation_id, chunk.index))


# ------------------------------------------------------------------------------------ statistics


@dataclass(frozen=True)
class PairedStatistics:
    """The paired comparison of Mode A and Mode B. ``None`` where a figure is undefined."""

    n: int
    alpha: float
    alternative: str
    mean_a: float | None
    mean_b: float | None
    mean_difference: float | None
    """Mean of ``delta_A - delta_B``. Negative means Mode A needed less rewriting."""
    sd_difference: float | None
    ci_low: float | None
    ci_high: float | None
    t_statistic: float | None
    df: int
    p_two_sided: float | None
    p_less: float | None
    """One-sided p-value for the hypothesis that Mode A's delta is lower."""
    cohens_d: float | None
    """``d_z``: the mean difference over the standard deviation of the differences."""
    wilcoxon_statistic: float | None
    wilcoxon_p_two_sided: float | None
    wilcoxon_p_less: float | None
    power: float | None
    """Achieved power of the t-test at the observed ``d_z``, ``n`` and ``alpha``: post hoc."""
    verdict: str
    """``pass``, ``fail`` or ``undefined``."""
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """The statistics as JSON-ready values."""
        return asdict(self)


def achieved_power(d: float, n: int, alpha: float, alternative: str) -> float:
    """Power of the paired t-test with ``n`` pairs to detect an effect ``d`` (``d_z``) at ``alpha``.

    From the noncentral t distribution with ``n - 1`` degrees of freedom and noncentrality
    ``d * sqrt(n)``. For ``less`` the rejection region is the lower tail only.
    """
    df = n - 1
    noncentrality = d * math.sqrt(n)
    if alternative == "less":
        critical = scipy_stats.t.ppf(alpha, df)
        return float(scipy_stats.nct.cdf(critical, df, noncentrality))
    critical = scipy_stats.t.ppf(1 - alpha / 2, df)
    upper = scipy_stats.nct.sf(critical, df, noncentrality)
    lower = scipy_stats.nct.cdf(-critical, df, noncentrality)
    return float(upper + lower)


def paired_statistics(
    deltas_a: Sequence[float],
    deltas_b: Sequence[float],
    *,
    alpha: float = 0.05,
    alternative: str = "two-sided",
    report_power: bool = True,
) -> PairedStatistics:
    """Test whether Mode A's deltas are lower than Mode B's, pair by pair.

    The verdict is ``pass`` only when the deciding p-value (``alternative``) is below ``alpha`` **and**
    the mean difference is negative, so a significant result in the wrong direction is a ``fail``.
    It is ``undefined`` with fewer than two pairs, or when every difference is the same, where the
    t statistic does not exist. See ``docs/EXPERIMENTS.md`` Stage 5 and ``docs/SPEC.md`` section 6.
    """
    if len(deltas_a) != len(deltas_b):
        raise ControlError(f"unpaired input: {len(deltas_a)} Mode A and {len(deltas_b)} Mode B")
    if alternative not in {"two-sided", "less"}:
        raise ControlError(f"alternative must be 'two-sided' or 'less', not '{alternative}'")

    n = len(deltas_a)
    differences = [a - b for a, b in zip(deltas_a, deltas_b, strict=True)]
    blank: dict[str, Any] = {
        "n": n,
        "alpha": alpha,
        "alternative": alternative,
        "mean_a": statistics.fmean(deltas_a) if n else None,
        "mean_b": statistics.fmean(deltas_b) if n else None,
        "mean_difference": statistics.fmean(differences) if n else None,
        "sd_difference": None,
        "ci_low": None,
        "ci_high": None,
        "t_statistic": None,
        "df": max(n - 1, 0),
        "p_two_sided": None,
        "p_less": None,
        "cohens_d": None,
        "wilcoxon_statistic": None,
        "wilcoxon_p_two_sided": None,
        "wilcoxon_p_less": None,
        "power": None,
    }
    if n < 2:
        return PairedStatistics(
            **blank, verdict="undefined", reason=f"{n} paired chunk(s); the test needs at least 2"
        )

    mean = statistics.fmean(differences)
    sd = statistics.stdev(differences)
    blank["sd_difference"] = sd
    if sd == 0:
        return PairedStatistics(
            **blank,
            verdict="undefined",
            reason="every paired difference is the same, so the t statistic does not exist",
        )

    df = n - 1
    standard_error = sd / math.sqrt(n)
    t_value = mean / standard_error
    margin = float(scipy_stats.t.ppf(1 - alpha / 2, df)) * standard_error
    p_two_sided = float(2 * scipy_stats.t.sf(abs(t_value), df))
    p_less = float(scipy_stats.t.cdf(t_value, df))
    d = mean / sd

    wilcoxon: dict[str, float | None] = {"statistic": None, "two-sided": None, "less": None}
    if any(difference != 0 for difference in differences):
        for side in ("two-sided", "less"):
            outcome = scipy_stats.wilcoxon(differences, alternative=side)
            wilcoxon[side] = float(outcome.pvalue)
            if side == "two-sided":
                wilcoxon["statistic"] = float(outcome.statistic)

    deciding = p_two_sided if alternative == "two-sided" else p_less
    if deciding < alpha and mean < 0:
        verdict, reason = "pass", f"Mode A is significantly lower (p = {deciding:.3g} < {alpha})"
    elif deciding < alpha:
        verdict, reason = "fail", f"Mode A is significantly higher (p = {deciding:.3g})"
    else:
        verdict, reason = "fail", f"no significant difference (p = {deciding:.3g} >= {alpha})"

    blank.update(
        ci_low=mean - margin,
        ci_high=mean + margin,
        t_statistic=t_value,
        p_two_sided=p_two_sided,
        p_less=p_less,
        cohens_d=d,
        wilcoxon_statistic=wilcoxon["statistic"],
        wilcoxon_p_two_sided=wilcoxon["two-sided"],
        wilcoxon_p_less=wilcoxon["less"],
        power=achieved_power(d, n, alpha, alternative) if report_power else None,
    )
    return PairedStatistics(**blank, verdict=verdict, reason=reason)


# ------------------------------------------------------------------------------------- the plan


@dataclass(frozen=True)
class ControlPlan:
    """What the experiment would do, computed without issuing anything."""

    n_creations: int
    n_chunks_total: int
    n_sample: int
    profile_calls: int
    model: str
    author_label: str
    estimated_input_tokens: int

    @property
    def rewrite_calls(self) -> int:
        """First attempts in both arms. Validation retries depend on the answers."""
        return 2 * self.n_sample

    @property
    def total_calls(self) -> int:
        """Every call the experiment would make before any retry."""
        return self.profile_calls + self.rewrite_calls


def plan_control(config: Config) -> ControlPlan:
    """Enumerate the experiment without touching a provider."""
    author_label = _author_label(config)
    texts = _load_texts(config)
    chunks = _chunk(texts, config)
    control = config.experiment.control
    sample = select_control_sample(
        chunks, control.sample_chunks, config.run.seed, stratify=control.stratify
    )

    model = config.llm.model_id or default_model(config.llm.provider) or ""
    window = declared_context_window(config.llm.provider, model or None) or 1_000_000
    bins = plan_packing(
        texts,
        context_window=window,
        budget_tokens=config.profile.context_budget_tokens,
        tokens_per_word=config.profile.tokens_per_word,
    )
    merged = 1 if len(bins) > 1 and config.profile.merge_when_multiple else 0

    per_word = config.profile.tokens_per_word
    corpus_tokens = sum(estimate_tokens(text, per_word) for text in texts.values())
    sample_tokens = sum(estimate_tokens(chunk.text, per_word) for chunk in sample)

    return ControlPlan(
        n_creations=len(texts),
        n_chunks_total=sum(len(creation) for creation in chunks.values()),
        n_sample=len(sample),
        profile_calls=len(bins) + merged,
        model=model or "the provider's own default",
        author_label=author_label,
        estimated_input_tokens=corpus_tokens + 2 * sample_tokens,
    )


# -------------------------------------------------------------------------------- the experiment


@dataclass
class ControlResult:
    """Everything one control experiment produced."""

    run_id: str
    run_dir: Path
    sample: list[Chunk]
    profile: ProfileResult
    mode_a: list[ChunkRewrite]
    mode_b: list[ChunkRewrite]
    pairs: list[dict[str, Any]]
    statistics: PairedStatistics
    manifest: dict[str, Any] = field(default_factory=dict)


def run_control(config: Config, *, run_id: str = "", progress: bool = True) -> ControlResult:
    """Run both arms over one sample, test the difference, and write an immutable run directory."""
    author_label = _author_label(config)
    run_id = run_id or build_run_id(config)
    run_dir = config.path(config.run.out_dir) / run_id
    if run_dir.exists():
        raise ControlError(
            f"'{run_id}' already exists at {run_dir}. Run artifacts are immutable (R9); start a new "
            "run id. The cache answers every call the earlier attempt already made."
        )

    run_dir.mkdir(parents=True)
    configure_logging(log_file=run_dir / "logs" / "run.log")
    started = datetime.now(UTC)
    (run_dir / "config.snapshot.yaml").write_text(
        yaml.safe_dump(config.to_dict(), sort_keys=True), encoding="utf-8", newline="\n"
    )
    code = _code_version(config.root)
    _dump(run_dir / "code_version.json", {**code, "started_utc": started.isoformat()})

    texts = _load_texts(config)
    chunks = _chunk(texts, config)
    control = config.experiment.control
    sample = select_control_sample(
        chunks, control.sample_chunks, config.run.seed, stratify=control.stratify
    )
    by_creation: dict[str, list[Chunk]] = {}
    for chunk in sample:
        by_creation.setdefault(chunk.creation_id, []).append(chunk)
    _write_chunks(run_dir, by_creation)
    logger.info("control.sample", n_chunks=len(sample), n_creations=len(by_creation))

    words_path = str(config.path(config.distance.function_words))
    function_words = frozenset(load_function_words(words_path))
    distance = build_distance(config.distance.metric, words_path)

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

    profile = extract_profile(texts, runner, run_index=RUN_INDEX, **_profile_options(config))
    _write_profile(run_dir, profile)
    _check_profile_sources(run_dir, config, profile, texts)

    validation = _validation(config)
    arm_options: dict[str, Any] = {
        "run_index": RUN_INDEX,
        "validation": validation,
        "max_retries": config.rewrite.max_retries,
        "max_output_tokens": config.rewrite.max_output_tokens,
        "temperature": config.llm.temperature,
    }
    mode_a = rewrite_chunks(sample, profile.profile.render(), runner, function_words, **arm_options)
    mode_b = rewrite_chunks_generic(sample, author_label, runner, function_words, **arm_options)

    pairs = [
        _pair(
            a,
            b,
            distance(a.original, a.rewrite).value if a.ok else None,
            distance(b.original, b.rewrite).value if b.ok else None,
        )
        for a, b in zip(mode_a, mode_b, strict=True)
    ]
    paired = [pair for pair in pairs if pair["paired"]]
    result_statistics = paired_statistics(
        [pair["delta_a"] for pair in paired],
        [pair["delta_b"] for pair in paired],
        alpha=control.alpha,
        alternative=control.alternative,
        report_power=control.report_power,
    )

    _write_pairs(run_dir / "pairs.csv", pairs)
    _write_arm(run_dir / "rewrites" / "mode_a.jsonl", mode_a, pairs, "delta_a")
    _write_arm(run_dir / "rewrites" / "mode_b.jsonl", mode_b, pairs, "delta_b")

    counts = {
        "n_sample": len(sample),
        "n_paired": len(paired),
        "n_failed_a": sum(1 for rewrite in mode_a if not rewrite.ok),
        "n_failed_b": sum(1 for rewrite in mode_b if not rewrite.ok),
        "n_creations": len(by_creation),
    }
    _dump(
        run_dir / "control.json",
        {
            "run_id": run_id,
            "author_label": author_label,
            "stratify": control.stratify,
            "seed": config.run.seed,
            **counts,
            "statistics": result_statistics.to_dict(),
        },
    )
    (run_dir / "summary.md").write_text(
        render_summary(run_id, counts, result_statistics), encoding="utf-8", newline="\n"
    )

    ledger_summary = summarize(read_ledger(run_dir / "calls.jsonl"))
    manifest = {
        "run_id": run_id,
        "experiment": "control",
        "started_utc": started.isoformat(),
        "ended_utc": datetime.now(UTC).isoformat(),
        "config_hash": config.config_hash(),
        "provider": config.llm.provider,
        "model_id": provider.model_id,
        **code,
        **counts,
        "verdict": result_statistics.verdict,
        "calls": asdict(ledger_summary),
    }
    _dump(run_dir / "manifest.json", manifest)
    logger.info(
        "control.complete",
        run_id=run_id,
        verdict=result_statistics.verdict,
        n_paired=len(paired),
        calls_live=runner.stats.live,
        calls_cached=runner.stats.cached,
    )

    return ControlResult(
        run_id=run_id,
        run_dir=run_dir,
        sample=sample,
        profile=profile,
        mode_a=mode_a,
        mode_b=mode_b,
        pairs=pairs,
        statistics=result_statistics,
        manifest=manifest,
    )


# ------------------------------------------------------------------------------------- artifacts


def _pair(
    a: ChunkRewrite, b: ChunkRewrite, delta_a: float | None, delta_b: float | None
) -> dict[str, Any]:
    """One row of ``pairs.csv``: one chunk under both arms (R7)."""
    paired = delta_a is not None and delta_b is not None
    return {
        "creation_id": a.creation_id,
        "chunk_index": a.chunk_index,
        "paired": paired,
        "delta_a": delta_a,
        "delta_b": delta_b,
        "difference": delta_a - delta_b if delta_a is not None and delta_b is not None else None,
        "status_a": str(a.status),
        "status_b": str(b.status),
        "reason_a": str(a.reason) if a.reason else "",
        "reason_b": str(b.reason) if b.reason else "",
        "attempts_a": a.attempts,
        "attempts_b": b.attempts,
    }


def _write_pairs(path: Path, pairs: list[dict[str, Any]]) -> None:
    """The per-chunk deltas of both arms; an empty cell is a chunk that arm could not measure."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pairs[0]), lineterminator="\n")
        writer.writeheader()
        for pair in pairs:
            writer.writerow({key: "" if value is None else value for key, value in pair.items()})


def _write_arm(
    path: Path, rewrites: list[ChunkRewrite], pairs: list[dict[str, Any]], delta_key: str
) -> None:
    """Every rewrite of one arm, with its delta, so a number traces back to its text (R7)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "creation_id": rewrite.creation_id,
                "chunk_index": rewrite.chunk_index,
                "status": str(rewrite.status),
                "reason": str(rewrite.reason) if rewrite.reason else "",
                "attempts": rewrite.attempts,
                "delta": pair[delta_key],
                "original": rewrite.original,
                "rewrite": rewrite.rewrite,
                "detail": rewrite.detail,
            },
            ensure_ascii=False,
        )
        for rewrite, pair in zip(rewrites, pairs, strict=True)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _figure(value: float | None, digits: int = 4) -> str:
    """A number for the summary, or a dash where it is undefined."""
    return "—" if value is None else f"{value:.{digits}f}"


def render_summary(run_id: str, counts: dict[str, int], result: PairedStatistics) -> str:
    """The experiment's written result, as markdown."""
    confidence = round(100 * (1 - result.alpha))
    rows = [
        ("pairs", f"{result.n} of {counts['n_sample']} sampled chunks"),
        ("left out", f"Mode A failed {counts['n_failed_a']}, Mode B failed {counts['n_failed_b']}"),
        ("mean delta, Mode A (profile)", _figure(result.mean_a)),
        ("mean delta, Mode B (generic)", _figure(result.mean_b)),
        ("mean difference A - B", _figure(result.mean_difference)),
        (
            f"{confidence}% confidence interval",
            f"{_figure(result.ci_low)} to {_figure(result.ci_high)}",
        ),
        ("t, df", f"{_figure(result.t_statistic, 3)}, {result.df}"),
        ("p, two-sided", _figure(result.p_two_sided, 6)),
        ("p, one-sided (A lower)", _figure(result.p_less, 6)),
        ("Cohen's d (paired, d_z)", _figure(result.cohens_d, 3)),
        ("Wilcoxon p, two-sided", _figure(result.wilcoxon_p_two_sided, 6)),
        ("Wilcoxon p, one-sided", _figure(result.wilcoxon_p_less, 6)),
        ("achieved power", _figure(result.power, 3)),
    ]
    return "\n".join(
        [
            "# Control experiment (M13)",
            "",
            f"Run `{run_id}`. Success metric 2 of `docs/SPEC.md` section 6.",
            "",
            f"**Verdict: {result.verdict}.** {result.reason[:1].upper()}{result.reason[1:]}. "
            "Decided by the "
            f"{result.alternative} p-value at alpha = {result.alpha}.",
            "",
            "| | |",
            "|---|---|",
            *[f"| {name} | {value} |" for name, value in rows],
            "",
            "## How to read this",
            "",
            "A negative difference means the profile left less to rewrite than the generic",
            "instruction did, which is what the method needs. A pass says the profile contributes",
            "beyond the model's memorized idea of the author. A fail is reported, not buried: it",
            "would mean the method rides on that prior, and the book's fallback is a held-out",
            "non-canonical corpus (`docs/EXPERIMENTS.md` Stage 5).",
            "",
            "The power is post hoc, at the observed effect. `pairs.csv` holds every chunk's two",
            "deltas, and `rewrites/` both arms' texts.",
            "",
        ]
    )


# ---------------------------------------------------------------------------------------- helpers


def _author_label(config: Config) -> str:
    """Mode B's author name, from configuration only (R1)."""
    label = config.corpus.author_label.strip()
    if not label:
        raise ControlError("Mode B needs corpus.author_label; it is empty in this configuration")
    return label


def _validation(config: Config) -> ValidationConfig:
    """Step 3's validation settings, the same for both arms."""
    checks = config.rewrite.validation
    return ValidationConfig(
        min_length_ratio=checks.min_length_ratio,
        max_length_ratio=checks.max_length_ratio,
        min_content_retention=checks.min_content_retention,
        strip_preamble=checks.strip_preamble,
        strip_code_fences=checks.strip_code_fences,
        refusal_scan_chars=checks.refusal_scan_chars,
    )


def _load_texts(config: Config) -> dict[str, str]:
    """The configured corpus subset."""
    sources = load_sources(config.path(config.corpus.sources))
    return load_corpus(
        sources,
        config.root,
        include_ids=config.corpus.include_ids,
        exclude_ids=config.corpus.exclude_ids,
        directories=directories_from_config(config),
    )


def _chunk(texts: dict[str, str], config: Config) -> dict[str, list[Chunk]]:
    """Step 2, over the configured subset."""
    return {
        name: chunk_text(text, config.chunking.P, creation_id=name) for name, text in texts.items()
    }


__all__ = [
    "ControlError",
    "ControlPlan",
    "ControlResult",
    "PairedStatistics",
    "achieved_power",
    "allocate",
    "paired_statistics",
    "plan_control",
    "render_summary",
    "run_control",
    "select_control_sample",
]
