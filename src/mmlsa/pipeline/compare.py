"""M9: comparing candidate models on identical chunks.

The approved book defers the choice of model to the proof of concept, and `docs/PLAN.md` M9 asks for
"a short written comparison of the candidate models on ten identical chunks, covering rewrite
fidelity, output cleanliness and latency". This module produces that comparison as an artifact rather
than as an afternoon of copying responses into a document, for the same reason every other number in
this project is produced by a command: a comparison assembled by hand cannot be repeated when a model
is deprecated, and it cannot be checked by anyone who was not there.

**Identical chunks is the whole point.** Every candidate rewrites the same passages, selected
deterministically from the configured corpus, so a difference between two models is a difference
between the models. The sample covers as many creations as it can rather than concentrating on the
longest one, because a model that handles verse and prose differently should be visible here and not
at M12.

**What is measured, and why each is here.**

* *Delta* — the FWED, the signal the whole method rests on. Not a quality score: a model that
  rewrites nothing scores zero and a model that paraphrases freely scores high, and neither is good.
  It is here so that the spread between models is visible before one is chosen.
* *Length ratio* and *content retention* — the specified validation checks (`docs/SPEC.md` Step 3).
  They answer "did it preserve the content", which is the fidelity half of the criterion.
* *Cleanliness* — whether the raw response needed a preamble or a code fence stripped before it could
  be measured. The pipeline strips both, so this never fails a run; it is worth knowing anyway,
  because a model that wraps every answer in chat is a model whose output has to be trusted to a
  regular expression on 7,500 calls.
* *Latency and tokens* — the cost of a full run, per model, extrapolated from a sample that is small
  enough to be free.

**What this module deliberately does not do.** It does not pick a winner. The acceptance criterion is
a written comparison, and the reading of the rewrites is a manual check that no test replaces
(`docs/TESTING.md` section 7). The artifacts are laid out to make that reading easy: originals and
rewrites side by side, one file per model.
"""

from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mmlsa.chunking import Chunk, chunk_text
from mmlsa.config import Config
from mmlsa.corpus.loader import directories_from_config, load_corpus, load_sources
from mmlsa.distance.base import StyleDistance
from mmlsa.distance.registry import build_distance
from mmlsa.distance.tokenize import load_function_words
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger
from mmlsa.llm.providers import build_provider, declared_context_window
from mmlsa.llm.runner import Job, Runner
from mmlsa.pipeline.profile import ProfileResult, extract_profile, plan_packing
from mmlsa.pipeline.rewrite import (
    ValidationConfig,
    build_rewrite_request,
    clean_response,
    validate_rewrite,
)
from mmlsa.utils.logging import get_logger
from mmlsa.utils.tokens import estimate_tokens

logger = get_logger(__name__)

DEFAULT_SAMPLE_SIZE = 10
"""The book's own figure: ten identical chunks."""


class ComparisonError(Exception):
    """Raised when a comparison cannot be set up or has nothing to measure."""


# ------------------------------------------------------------------------------------- candidates


@dataclass(frozen=True)
class Candidate:
    """One model under comparison, named as ``provider`` or ``provider:model_id``."""

    provider: str
    model_id: str | None = None

    @property
    def label(self) -> str:
        """How this candidate is named in every artifact. Stable, and safe as a directory name."""
        return f"{self.provider}:{self.model_id}" if self.model_id else self.provider

    @property
    def slug(self) -> str:
        """The label reduced to something a filesystem accepts on every platform."""
        return "".join(character if character.isalnum() else "_" for character in self.label)

    @classmethod
    def parse(cls, specification: str) -> Candidate:
        """Parse ``gemini`` or ``gemini:gemini-2.5-flash``.

        A bare provider name means "whatever model that provider defaults to", which is convenient
        and also exactly the thing worth being explicit about before spending money, so the plan
        prints the resolved identifier either way.
        """
        text = specification.strip()
        if not text:
            raise ComparisonError("empty model specification; expected provider[:model_id]")

        provider, separator, model_id = text.partition(":")
        if separator and not model_id.strip():
            raise ComparisonError(
                f"'{specification}' names a provider but no model. Write 'provider' for its "
                "default, or 'provider:model_id' for a specific one."
            )
        return cls(provider=provider.strip(), model_id=model_id.strip() or None)


# ------------------------------------------------------------------------------------ the sample


def select_sample(
    chunks: dict[str, list[Chunk]],
    size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = 0,
) -> list[Chunk]:
    """Choose the passages every candidate will rewrite.

    Round-robin across creations rather than a flat sample, because the creations differ in length by
    an order of magnitude and a flat sample would be dominated by the longest one. Ten chunks drawn
    from ten creations tell you more about a model than ten chunks from one.

    Deterministic in ``(chunks, size, seed)`` (R8): the seed chooses where within each creation to
    start, and everything else is sorted. Two comparisons with the same seed measure the same
    passages, which is what makes a model added later comparable to the ones measured today.
    """
    populated = {name: creation for name, creation in sorted(chunks.items()) if creation}
    if not populated:
        raise ComparisonError("the configured corpus produced no chunks to sample")

    sample: list[Chunk] = []
    for round_index in range(size):
        for creation in populated.values():
            if len(sample) >= size:
                return sample
            candidate = creation[(seed + round_index) % len(creation)]
            if candidate not in sample:
                sample.append(candidate)

    return sample


# ------------------------------------------------------------------------------------ the results


@dataclass(frozen=True)
class ChunkComparison:
    """One candidate's attempt at one chunk."""

    model: str
    creation_id: str
    chunk_index: int
    ok: bool
    reason: str
    delta: float
    length_ratio: float
    content_retention: float
    needed_cleaning: bool
    latency_ms: int
    input_tokens: int
    output_tokens: int
    original: str
    raw_response: str
    rewrite: str

    def row(self) -> dict[str, Any]:
        """The comparison table's row, without the texts."""
        return {
            "model": self.model,
            "creation_id": self.creation_id,
            "chunk_index": self.chunk_index,
            "ok": self.ok,
            "reason": self.reason,
            "delta": round(self.delta, 6),
            "length_ratio": round(self.length_ratio, 4),
            "content_retention": round(self.content_retention, 4),
            "needed_cleaning": self.needed_cleaning,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass
class ModelComparison:
    """Everything one candidate produced."""

    candidate: Candidate
    model_version: str
    profile: ProfileResult | None
    chunks: list[ChunkComparison] = field(default_factory=list)
    profile_calls: int = 0
    error: str = ""

    @property
    def label(self) -> str:
        """The candidate's name."""
        return self.candidate.label

    @property
    def usable(self) -> list[ChunkComparison]:
        """The chunks that produced a measurable rewrite."""
        return [chunk for chunk in self.chunks if chunk.ok]

    def _mean(self, attribute: str) -> float:
        """The mean of one measure over the usable chunks, or zero when there are none."""
        values = [float(getattr(chunk, attribute)) for chunk in self.usable]
        return statistics.fmean(values) if values else 0.0

    def summary(self) -> dict[str, Any]:
        """The per-model line of the comparison table.

        The standard deviation of the delta is reported next to its mean because a model with a
        middling mean and a huge spread is a different proposition from a steady one, and only the
        pair distinguishes them.
        """
        deltas = [chunk.delta for chunk in self.usable]
        latencies = [chunk.latency_ms for chunk in self.chunks]
        return {
            "model": self.label,
            "model_version": self.model_version,
            "n_chunks": len(self.chunks),
            "n_ok": len(self.usable),
            "mean_delta": round(self._mean("delta"), 4),
            "sd_delta": round(statistics.stdev(deltas), 4) if len(deltas) > 1 else 0.0,
            "mean_length_ratio": round(self._mean("length_ratio"), 3),
            "mean_content_retention": round(self._mean("content_retention"), 3),
            "needed_cleaning": sum(1 for chunk in self.chunks if chunk.needed_cleaning),
            "median_latency_ms": int(statistics.median(latencies)) if latencies else 0,
            "input_tokens": sum(chunk.input_tokens for chunk in self.chunks),
            "output_tokens": sum(chunk.output_tokens for chunk in self.chunks),
            "profile_calls": self.profile_calls,
            "error": self.error,
        }


@dataclass
class ComparisonResult:
    """The whole comparison: several candidates over one shared sample."""

    sample: list[Chunk]
    models: list[ModelComparison]
    seed: int

    def table(self) -> list[dict[str, Any]]:
        """One summary row per candidate."""
        return [model.summary() for model in self.models]


# ------------------------------------------------------------------------------------- the plan


@dataclass(frozen=True)
class ComparisonPlan:
    """What a comparison would cost, computed without issuing anything."""

    candidates: list[tuple[str, str, int]]
    """``(label, resolved model, profile calls)`` per candidate."""

    n_chunks: int
    estimated_input_tokens: int

    @property
    def total_calls(self) -> int:
        """Every call the comparison would make."""
        return sum(profile_calls + self.n_chunks for _, _, profile_calls in self.candidates)


def plan_comparison(
    config: Config,
    candidates: list[Candidate],
    *,
    size: int = DEFAULT_SAMPLE_SIZE,
) -> ComparisonPlan:
    """Enumerate the comparison without touching a provider.

    Profile extraction is the expensive half and it is easy to underestimate: it sends the **whole
    configured corpus** to every candidate, once each, and a model with a smaller context window
    needs proportionally more calls to do it. Point ``compare`` at a small subset unless you mean it.
    """
    texts = _load_texts(config)
    chunks = _chunk(texts, config)
    sample = select_sample(chunks, size, config.run.seed)

    rows: list[tuple[str, str, int]] = []
    for candidate in candidates:
        window = declared_context_window(candidate.provider, candidate.model_id) or 1_000_000
        bins = plan_packing(
            texts,
            context_window=window,
            budget_tokens=config.profile.context_budget_tokens,
            tokens_per_word=config.profile.tokens_per_word,
        )
        merged = 1 if len(bins) > 1 and config.profile.merge_when_multiple else 0
        rows.append((candidate.label, _resolved_model(candidate), len(bins) + merged))

    corpus_tokens = sum(
        estimate_tokens(text, config.profile.tokens_per_word) for text in texts.values()
    )
    sample_tokens = sum(
        estimate_tokens(chunk.text, config.profile.tokens_per_word) for chunk in sample
    )

    return ComparisonPlan(
        candidates=rows,
        n_chunks=len(sample),
        estimated_input_tokens=len(candidates) * (corpus_tokens + sample_tokens),
    )


# --------------------------------------------------------------------------------- the comparison


def compare_models(
    config: Config,
    candidates: list[Candidate],
    directory: Path,
    *,
    size: int = DEFAULT_SAMPLE_SIZE,
) -> ComparisonResult:
    """Run every candidate over the same sample, write the artifacts, return the measurements.

    A candidate that cannot be built at all — a missing extra, a missing key — is recorded with its
    error and the comparison continues. Comparing two models is still worth doing when the third has
    no key, and stopping would mean the two that do work are never measured.

    ``directory`` is required rather than optional because every call has to reach a ledger (R2), and
    a comparison whose calls were not recorded is not evidence.
    """
    if not candidates:
        raise ComparisonError("no candidate models to compare")

    texts = _load_texts(config)
    chunks = _chunk(texts, config)
    sample = select_sample(chunks, size, config.run.seed)

    words_path = str(config.path(config.distance.function_words))
    function_words = frozenset(load_function_words(words_path))
    distance = build_distance(config.distance.metric, words_path)
    validation = ValidationConfig(
        min_length_ratio=config.rewrite.validation.min_length_ratio,
        max_length_ratio=config.rewrite.validation.max_length_ratio,
        min_content_retention=config.rewrite.validation.min_content_retention,
        strip_preamble=config.rewrite.validation.strip_preamble,
        strip_code_fences=config.rewrite.validation.strip_code_fences,
    )

    directory.mkdir(parents=True, exist_ok=True)
    cache = ResponseCache(config.path(config.llm.cache_dir), mode=config.llm.mode)
    ledger = Ledger(directory / "calls.jsonl", run_id=directory.name)
    results: list[ModelComparison] = []

    for candidate in candidates:
        logger.info("compare.candidate", model=candidate.label, chunks=len(sample))
        results.append(
            _measure(
                candidate,
                config=config,
                texts=texts,
                sample=sample,
                cache=cache,
                ledger=ledger,
                function_words=function_words,
                distance=distance,
                validation=validation,
            )
        )

    result = ComparisonResult(sample=sample, models=results, seed=config.run.seed)
    write_comparison(result, directory)
    return result


def _measure(
    candidate: Candidate,
    *,
    config: Config,
    texts: dict[str, str],
    sample: list[Chunk],
    cache: ResponseCache,
    ledger: Ledger,
    function_words: frozenset[str],
    distance: StyleDistance,
    validation: ValidationConfig,
) -> ModelComparison:
    """Extract one profile and rewrite the sample with a single candidate."""
    try:
        provider = build_provider(
            candidate.provider,
            model_id=candidate.model_id,
            cache=cache,
            timeout_seconds=config.llm.timeout_seconds,
        )
    except Exception as exc:
        # Deliberately broad: a candidate that cannot be built at all must not stop the two
        # that can. The error is recorded against that candidate and reported in the summary.
        logger.warning("compare.unavailable", model=candidate.label, error=str(exc))
        return ModelComparison(
            candidate=candidate,
            model_version="",
            profile=None,
            error=f"{type(exc).__name__}: {exc}",
        )

    runner = Runner(
        provider=provider,
        cache=cache,
        ledger=ledger,
        concurrency=config.llm.concurrency,
        requests_per_minute=config.llm.requests_per_minute,
        tokens_per_minute=config.llm.tokens_per_minute,
        max_transient_retries=config.llm.max_transient_retries,
        mode=config.llm.mode,
    )

    try:
        profile = extract_profile(
            texts,
            runner,
            run_index=1,
            structured=config.profile.structured_output,
            budget_tokens=config.profile.context_budget_tokens,
            tokens_per_word=config.profile.tokens_per_word,
            merge_when_multiple=config.profile.merge_when_multiple,
            max_output_tokens=config.profile.max_output_tokens,
            temperature=config.llm.temperature,
        )
    except Exception as exc:
        # Same reasoning: without a profile there is nothing to rewrite against, so this
        # candidate is recorded as unmeasured and the comparison continues.
        logger.warning("compare.profile_failed", model=candidate.label, error=str(exc))
        return ModelComparison(
            candidate=candidate,
            model_version=provider.model_id,
            profile=None,
            error=f"profile extraction failed: {type(exc).__name__}: {exc}",
        )

    profile_text = profile.profile.render()
    jobs = [
        Job(
            request=build_rewrite_request(
                chunk.text,
                profile_text,
                max_output_tokens=config.rewrite.max_output_tokens,
                temperature=config.llm.temperature,
            ),
            creation_id=chunk.creation_id,
            chunk_index=chunk.index,
            run_index=1,
        )
        for chunk in sample
    ]

    by_key = {
        (result.job.creation_id, result.job.chunk_index): result for result in runner.run(jobs)
    }
    model_version = ""
    measurements: list[ChunkComparison] = []

    for chunk in sample:
        result = by_key[(chunk.creation_id, chunk.index)]
        model_version = model_version or (result.response.model_version if result.response else "")
        measurements.append(
            _measure_chunk(
                candidate,
                chunk,
                result,
                function_words=function_words,
                distance=distance,
                validation=validation,
            )
        )

    return ModelComparison(
        candidate=candidate,
        model_version=model_version or provider.model_id,
        profile=profile,
        chunks=measurements,
        profile_calls=len(profile.partials) + (1 if profile.merged else 0),
    )


def _measure_chunk(
    candidate: Candidate,
    chunk: Chunk,
    result: Any,
    *,
    function_words: frozenset[str],
    distance: StyleDistance,
    validation: ValidationConfig,
) -> ChunkComparison:
    """Turn one response into one row of the comparison.

    ``needed_cleaning`` compares the raw response against the cleaned one. The pipeline strips
    preambles and code fences, so this never changes a verdict; it is recorded because "how often did
    this model wrap its answer in chat" is a property worth knowing before trusting a regular
    expression with several thousand responses.
    """
    if result.response is None:
        return ChunkComparison(
            model=candidate.label,
            creation_id=chunk.creation_id,
            chunk_index=chunk.index,
            ok=False,
            reason=result.error_class or "call_failed",
            delta=0.0,
            length_ratio=0.0,
            content_retention=0.0,
            needed_cleaning=False,
            latency_ms=0,
            input_tokens=0,
            output_tokens=0,
            original=chunk.text,
            raw_response="",
            rewrite="",
        )

    raw = result.response.text
    outcome = validate_rewrite(chunk.text, raw, function_words, validation)
    cleaned = outcome.cleaned
    words_original = len(chunk.text.split())
    words_rewrite = len(cleaned.split())

    return ChunkComparison(
        model=candidate.label,
        creation_id=chunk.creation_id,
        chunk_index=chunk.index,
        ok=outcome.ok,
        reason=str(outcome.reason) if outcome.reason else "",
        delta=distance(chunk.text, cleaned).value if outcome.ok else 0.0,
        length_ratio=words_rewrite / words_original if words_original else 0.0,
        content_retention=outcome.detail.get("content_retention", 0.0),
        needed_cleaning=clean_response(raw, validation) != raw.strip(),
        latency_ms=result.response.latency_ms,
        input_tokens=result.response.input_tokens,
        output_tokens=result.response.output_tokens,
        original=chunk.text,
        raw_response=raw,
        rewrite=cleaned,
    )


# ------------------------------------------------------------------------------------- artifacts


def write_comparison(result: ComparisonResult, directory: Path) -> None:
    """Write the comparison so it can be read, not just parsed.

    Four artifacts. ``summary.md`` is the acceptance criterion's "short written comparison".
    ``comparison.csv`` is the same numbers for a spreadsheet. ``rewrites/`` holds each passage beside
    each model's version of it, which is what `docs/TESTING.md` section 7 asks a human to read.
    ``profiles/`` holds what each model said the style was, which is the second manual check.
    """
    directory.mkdir(parents=True, exist_ok=True)

    with (directory / "comparison.csv").open("w", encoding="utf-8", newline="") as handle:
        rows = [chunk.row() for model in result.models for chunk in model.chunks]
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    (directory / "summary.md").write_text(render_summary(result), encoding="utf-8")
    (directory / "summary.json").write_text(
        json.dumps(
            {"seed": result.seed, "n_chunks": len(result.sample), "models": result.table()},
            indent=2,
        ),
        encoding="utf-8",
    )

    for model in result.models:
        if model.profile is not None:
            profiles = directory / "profiles"
            profiles.mkdir(exist_ok=True)
            (profiles / f"{model.candidate.slug}.json").write_text(
                json.dumps(model.profile.to_dict(), indent=2), encoding="utf-8"
            )

    _write_side_by_side(result, directory / "rewrites")


def _write_side_by_side(result: ComparisonResult, directory: Path) -> None:
    """One file per sampled chunk: the original, then every model's rewrite of it.

    Grouped by chunk rather than by model, because the manual check is a comparison and a reader
    should not have to hold a passage in their head while opening another file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    by_chunk: dict[tuple[str, int], list[ChunkComparison]] = {}
    for model in result.models:
        for chunk in model.chunks:
            by_chunk.setdefault((chunk.creation_id, chunk.chunk_index), []).append(chunk)

    for (creation_id, index), attempts in sorted(by_chunk.items()):
        lines = [f"# {creation_id} chunk {index}", "", "## original", "", attempts[0].original, ""]
        for attempt in attempts:
            verdict = "ok" if attempt.ok else f"REJECTED ({attempt.reason})"
            lines += [
                f"## {attempt.model} — delta {attempt.delta:.4f}, {verdict}",
                "",
                attempt.rewrite or "(no usable text)",
                "",
            ]
        (directory / f"{creation_id}_{index:04d}.md").write_text("\n".join(lines), encoding="utf-8")


def render_summary(result: ComparisonResult) -> str:
    """The written comparison M9 asks for, as markdown."""
    header = (
        "| model | resolved | ok | mean delta | sd | length | retention | cleaned | "
        "latency ms | tokens in | tokens out |"
    )
    divider = "|---|---|---|---|---|---|---|---|---|---|---|"
    rows = []
    for summary in result.table():
        rows.append(
            f"| {summary['model']} | {summary['model_version'] or '—'} | "
            f"{summary['n_ok']}/{summary['n_chunks']} | {summary['mean_delta']} | "
            f"{summary['sd_delta']} | {summary['mean_length_ratio']} | "
            f"{summary['mean_content_retention']} | {summary['needed_cleaning']} | "
            f"{summary['median_latency_ms']} | {summary['input_tokens']} | "
            f"{summary['output_tokens']} |"
        )

    failures = [
        f"- **{summary['model']}** could not be measured: {summary['error']}"
        for summary in result.table()
        if summary["error"]
    ]

    return "\n".join(
        [
            "# Model comparison (M9)",
            "",
            f"{len(result.sample)} identical chunks, seed {result.seed}.",
            "",
            header,
            divider,
            *rows,
            "",
            *([*failures, ""] if failures else []),
            "## How to read this",
            "",
            "The delta is the signal, not a score. A model that changes nothing scores near zero and",
            "a model that paraphrases freely scores high; neither is what the method wants. What to",
            "look for is a **middling delta with good content retention**, meaning the style moved",
            "and the subject matter did not.",
            "",
            "`length` and `retention` are the specified validation checks. `cleaned` counts responses",
            "that arrived wrapped in a preamble or a code fence — harmless, since the pipeline strips",
            "both, but a model that does it every time is one more thing trusting a pattern.",
            "",
            "**Then read the rewrites.** `rewrites/` holds each passage with every model's version",
            "beneath it. No table answers the question `docs/TESTING.md` section 7 asks: is the model",
            "quietly modernizing spelling? That would inflate every delta uniformly and look like a",
            "working method while measuring nothing.",
            "",
            "`profiles/` holds what each model said the style was. A profile that would fit any",
            "English text makes the control experiment the whole story.",
            "",
        ]
    )


# ---------------------------------------------------------------------------------------- helpers


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


def _resolved_model(candidate: Candidate) -> str:
    """The model identifier a candidate will actually use, for the plan."""
    from mmlsa.llm.providers import default_model

    return candidate.model_id or default_model(candidate.provider) or "the provider's own default"


__all__ = [
    "Candidate",
    "ChunkComparison",
    "ComparisonError",
    "ComparisonPlan",
    "ComparisonResult",
    "ModelComparison",
    "compare_models",
    "plan_comparison",
    "render_summary",
    "select_sample",
    "write_comparison",
]
