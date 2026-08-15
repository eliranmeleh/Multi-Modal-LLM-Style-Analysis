"""Step 3 — LLM rewriting, and the response handling that protects the measurement.

Within a run, each chunk is rewritten once under that run's profile, with instructions to preserve
content and change only stylistic features. Across the `M` runs each chunk therefore receives `M`
rewrites, each paired with an independent profile.

**The validation is not defensive programming; it is part of the measurement.** The style distance
reads the difference between a chunk and its rewrite. A refusal, a chatty preamble or a wholesale
paraphrase all produce a large difference, and none of them means what a large difference is supposed
to mean. Without these checks the pipeline would manufacture false positives out of the model's
manners. The approved book does not cover response handling because it specifies a method rather
than an engineering artifact; the checks are recorded in ``docs/DECISIONS.md`` I5.

One case is easy to get backwards: **a rewrite identical to the original is valid**, not a failure.
It means the model found nothing to change, which is exactly what an authentic chunk should produce,
and it yields a delta of zero.

See ``docs/SPEC.md`` section 3, Step 3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from mmlsa import prompts
from mmlsa.chunking import Chunk
from mmlsa.distance.base import StyleDistance
from mmlsa.distance.tokenize import tokenize
from mmlsa.llm.base import LLMRequest
from mmlsa.llm.runner import Job, Runner
from mmlsa.pipeline.score import ChunkDelta, ChunkStatus
from mmlsa.utils.logging import get_logger
from mmlsa.utils.text import strip_code_fences

logger = get_logger(__name__)

PREAMBLE = re.compile(
    r"^\s*(here(?:\s+is|\s?['’]s)|sure|certainly|rewritten|rewrite|below is)[^\n]*:\s*\n",
    re.IGNORECASE,
)
"""A leading conversational line, from ``docs/SPEC.md`` Step 3.

Anchored to the start and required to end in a colon and a newline, so it cannot eat a line of the
passage itself. Everything after it is preserved verbatim, line breaks included.

**Corrected from the specification's literal text**, which read ``here (is|'s)`` with a space before
the group. That matches "here 's" and not the contraction "here's" — which is the commoner opening of
the two. An unstripped preamble is not a crash: it is silently measured as part of the passage and
inflates that chunk's delta. See ``docs/DECISIONS.md`` I23. The typographic apostrophe is accepted
too, since a model response has not been through the corpus normalization that folds it.
"""

REFUSAL_MARKERS = (
    "i cannot",
    "i can't",
    "i'm sorry",
    "i am sorry",
    "as an ai",
    "i'm unable",
    "i am unable",
    "i won't",
    "i will not",
)
"""Lower-cased markers of a refusal. A refusal is not a rewrite, and must never be scored as one."""


class RewriteStatus(StrEnum):
    """Outcome of rewriting one chunk."""

    OK = "ok"
    FAILED = "failed"


class FailureReason(StrEnum):
    """Why a rewrite was rejected. Recorded so failures can be counted by kind, not just totalled."""

    EMPTY = "empty"
    REFUSAL = "refusal"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    CONTENT_LOST = "content_lost"
    CALL_FAILED = "call_failed"


@dataclass(frozen=True)
class ValidationConfig:
    """Thresholds for accepting a rewrite. Mirrors ``rewrite.validation`` in the configuration."""

    min_length_ratio: float = 0.60
    max_length_ratio: float = 1.60
    min_content_retention: float = 0.50
    strip_preamble: bool = True
    strip_code_fences: bool = True


@dataclass(frozen=True)
class ValidationOutcome:
    """Whether a response is usable, and if not, why."""

    ok: bool
    cleaned: str
    reason: FailureReason | None = None
    detail: dict[str, float] = field(default_factory=dict)


@dataclass
class ChunkRewrite:
    """One chunk's rewrite within one run, with the accounting Step 5 needs."""

    creation_id: str
    chunk_index: int
    original: str
    rewrite: str
    status: RewriteStatus
    attempts: int
    n_words_original: int
    n_words_rewrite: int
    reason: FailureReason | None = None
    detail: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Whether this chunk produced a usable rewrite."""
        return self.status is RewriteStatus.OK


@dataclass
class CreationRewriteReport:
    """Failure accounting for one creation in one run, written into the run manifest."""

    creation_id: str
    run_index: int
    n_chunks: int
    n_ok: int
    n_failed: int
    n_retried: int
    reasons: dict[str, int] = field(default_factory=dict)
    unreliable: bool = False

    @property
    def failed_fraction(self) -> float:
        """Share of this creation's chunks that produced no usable rewrite."""
        return self.n_failed / self.n_chunks if self.n_chunks else 0.0


# ------------------------------------------------------------------------------------- cleaning


def strip_preamble(text: str) -> str:
    """Remove a leading conversational line, if present.

    Applied once. A response with two lines of chat is a response that failed to follow the
    instruction, and repeatedly peeling lines off would eventually start eating the passage.
    """
    return PREAMBLE.sub("", text, count=1)


def clean_response(text: str, config: ValidationConfig) -> str:
    """Reduce a raw response to the rewritten passage alone.

    Fences are removed before the preamble, because a preamble inside a fenced block would otherwise
    still be wrapped when the pattern is tested.
    """
    cleaned = text
    if config.strip_code_fences:
        cleaned = strip_code_fences(cleaned)
    if config.strip_preamble:
        cleaned = strip_preamble(cleaned)
    return cleaned.strip()


# ------------------------------------------------------------------------------------ validation


def content_words(text: str, function_words: frozenset[str]) -> set[str]:
    """The set of non-function word **types** in a text.

    Types rather than tokens, and a set rather than a bag: the question is whether the subject matter
    survived, not whether word frequencies did. Frequencies are the style signal, and requiring them
    to be preserved would forbid the very rewriting the method asks for.
    """
    return {token for token in tokenize(text) if token not in function_words}


def content_retention(original: str, rewrite: str, function_words: frozenset[str]) -> float:
    """Overlap coefficient over content-word types: ``|A and B| / min(|A|, |B|)``.

    The overlap coefficient rather than Jaccard, because a rewrite that legitimately adds a few words
    should not be penalised for the addition; what matters is how much of the smaller vocabulary is
    shared. A chunk with no content words at all is vacuously fully retained.
    """
    left = content_words(original, function_words)
    right = content_words(rewrite, function_words)

    if not left or not right:
        return 1.0 if not left and not right else 0.0
    return len(left & right) / min(len(left), len(right))


def validate_rewrite(
    original: str,
    response: str,
    function_words: frozenset[str],
    config: ValidationConfig | None = None,
) -> ValidationOutcome:
    """Apply the four specified checks in order, cheapest first.

    Order matters for the reported reason rather than for the verdict: an empty response is reported
    as empty rather than as content loss, which is what a reader needs to know.
    """
    config = config or ValidationConfig()
    cleaned = clean_response(response, config)

    if not cleaned:
        return ValidationOutcome(ok=False, cleaned=cleaned, reason=FailureReason.EMPTY)

    lowered = cleaned.lower()
    if any(marker in lowered for marker in REFUSAL_MARKERS):
        return ValidationOutcome(ok=False, cleaned=cleaned, reason=FailureReason.REFUSAL)

    n_original = len(original.split())
    n_rewrite = len(cleaned.split())
    ratio = n_rewrite / n_original if n_original else 0.0

    if ratio < config.min_length_ratio:
        return ValidationOutcome(
            ok=False,
            cleaned=cleaned,
            reason=FailureReason.TOO_SHORT,
            detail={"length_ratio": ratio},
        )
    if ratio > config.max_length_ratio:
        return ValidationOutcome(
            ok=False, cleaned=cleaned, reason=FailureReason.TOO_LONG, detail={"length_ratio": ratio}
        )

    retention = content_retention(original, cleaned, function_words)
    if retention < config.min_content_retention:
        return ValidationOutcome(
            ok=False,
            cleaned=cleaned,
            reason=FailureReason.CONTENT_LOST,
            detail={"length_ratio": ratio, "content_retention": retention},
        )

    return ValidationOutcome(
        ok=True,
        cleaned=cleaned,
        detail={"length_ratio": ratio, "content_retention": retention},
    )


# --------------------------------------------------------------------------------------- requests


def build_rewrite_request(
    chunk_text: str,
    profile_text: str,
    *,
    retry: bool = False,
    max_output_tokens: int = 2048,
) -> LLMRequest:
    """Render one rewrite call.

    A retry is the **same prompt** with a clarification appended, as specified. Because the prompt
    differs, it is a separate cache entry, so a retry is never served the response that failed.
    """
    prompt = prompts.render(prompts.REWRITE, profile=profile_text, passage=chunk_text)
    version = prompts.template_version(prompts.REWRITE)

    if retry:
        prompt += prompts.load_template(prompts.REWRITE_RETRY)
        version += prompts.template_version(prompts.REWRITE_RETRY)

    return LLMRequest(
        prompt=prompt,
        tag="rewrite",
        max_output_tokens=max_output_tokens,
        prompt_schema_version=version,
    )


# ------------------------------------------------------------------------------------ the worker


def rewrite_chunks(
    chunks: list[Chunk],
    profile_text: str,
    runner: Runner,
    function_words: frozenset[str],
    *,
    run_index: int = 1,
    validation: ValidationConfig | None = None,
    max_retries: int = 2,
    max_output_tokens: int = 2048,
) -> list[ChunkRewrite]:
    """Rewrite every chunk, retrying the ones whose response fails validation.

    Retries are **batched**: one round submits every outstanding chunk at once, so concurrency is
    preserved rather than collapsing to a serial retry per chunk. The rounds are bounded by
    ``max_retries``, and the results come back in chunk order regardless of completion order.

    Content-validation retries are counted separately from the transport retries the runner handles.
    They are different problems: one is the network, the other is the model's behaviour, and
    conflating them would hide whichever is actually happening.
    """
    validation = validation or ValidationConfig()
    outcomes: dict[tuple[str, int], ChunkRewrite] = {}
    attempts: dict[tuple[str, int], int] = {}
    outstanding = list(chunks)

    for round_index in range(max_retries + 1):
        if not outstanding:
            break

        jobs = [
            Job(
                request=build_rewrite_request(
                    chunk.text,
                    profile_text,
                    retry=round_index > 0,
                    max_output_tokens=max_output_tokens,
                ),
                creation_id=chunk.creation_id,
                chunk_index=chunk.index,
                run_index=run_index,
            )
            for chunk in outstanding
        ]

        results = runner.run(jobs)
        by_key = {(r.job.creation_id, r.job.chunk_index): r for r in results}
        still_outstanding: list[Chunk] = []

        for chunk in outstanding:
            key = (chunk.creation_id, chunk.index)
            attempts[key] = attempts.get(key, 0) + 1
            result = by_key[key]

            if result.response is None:
                outcomes[key] = _failed(chunk, attempts[key], FailureReason.CALL_FAILED, "")
                still_outstanding.append(chunk)
                continue

            outcome = validate_rewrite(chunk.text, result.response.text, function_words, validation)
            if outcome.ok:
                outcomes[key] = ChunkRewrite(
                    creation_id=chunk.creation_id,
                    chunk_index=chunk.index,
                    original=chunk.text,
                    rewrite=outcome.cleaned,
                    status=RewriteStatus.OK,
                    attempts=attempts[key],
                    n_words_original=len(chunk.text.split()),
                    n_words_rewrite=len(outcome.cleaned.split()),
                    detail=outcome.detail,
                )
            else:
                outcomes[key] = _failed(
                    chunk, attempts[key], outcome.reason, outcome.cleaned, outcome.detail
                )
                still_outstanding.append(chunk)

        if still_outstanding and round_index < max_retries:
            logger.info(
                "rewrite.retrying",
                run_index=run_index,
                round=round_index + 1,
                n_chunks=len(still_outstanding),
            )
        outstanding = still_outstanding

    return [outcomes[(chunk.creation_id, chunk.index)] for chunk in chunks]


def _failed(
    chunk: Chunk,
    attempts: int,
    reason: FailureReason | None,
    cleaned: str,
    detail: dict[str, float] | None = None,
) -> ChunkRewrite:
    """Build a failed result, keeping whatever text came back for inspection."""
    return ChunkRewrite(
        creation_id=chunk.creation_id,
        chunk_index=chunk.index,
        original=chunk.text,
        rewrite=cleaned,
        status=RewriteStatus.FAILED,
        attempts=attempts,
        n_words_original=len(chunk.text.split()),
        n_words_rewrite=len(cleaned.split()),
        reason=reason,
        detail=detail or {},
    )


def to_chunk_deltas(
    rewrites: list[ChunkRewrite],
    distance: StyleDistance,
) -> list[ChunkDelta]:
    """Measure each rewrite and hand Step 5 what it needs.

    This is the seam between Step 3 and Step 4. A failed chunk still produces a ``ChunkDelta``, with
    ``status`` set to failed and a delta of zero, because Step 5 has to *count* it in order to report
    the failed fraction. The zero is never averaged in: ``aggregate_run`` excludes failed chunks from
    both the numerator and the divisor.
    """
    deltas: list[ChunkDelta] = []
    for rewrite in rewrites:
        if not rewrite.ok:
            deltas.append(
                ChunkDelta(
                    creation_id=rewrite.creation_id,
                    chunk_index=rewrite.chunk_index,
                    delta=0.0,
                    n_words=rewrite.n_words_original,
                    status=ChunkStatus.FAILED,
                )
            )
            continue

        result = distance(rewrite.original, rewrite.rewrite)
        deltas.append(
            ChunkDelta(
                creation_id=rewrite.creation_id,
                chunk_index=rewrite.chunk_index,
                delta=result.value,
                n_words=rewrite.n_words_original,
                status=ChunkStatus.OK,
                degenerate=result.degenerate,
            )
        )
    return deltas


def report_creation(
    creation_id: str,
    run_index: int,
    rewrites: list[ChunkRewrite],
    *,
    max_failed_fraction: float = 0.02,
) -> CreationRewriteReport:
    """Summarize one creation's rewrite outcomes for the run manifest.

    A creation whose failed fraction exceeds the bound is flagged **unreliable** rather than dropped:
    its score is still computed from the chunks that did work, but the report says how much of it is
    missing, so a reader can judge the number rather than trust it.
    """
    failed = [r for r in rewrites if not r.ok]
    reasons: dict[str, int] = {}
    for rewrite in failed:
        name = rewrite.reason.value if rewrite.reason else "unknown"
        reasons[name] = reasons.get(name, 0) + 1

    report = CreationRewriteReport(
        creation_id=creation_id,
        run_index=run_index,
        n_chunks=len(rewrites),
        n_ok=len(rewrites) - len(failed),
        n_failed=len(failed),
        n_retried=sum(1 for r in rewrites if r.attempts > 1),
        reasons=reasons,
    )
    report.unreliable = report.failed_fraction > max_failed_fraction
    return report
