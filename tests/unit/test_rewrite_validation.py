"""Step 3 — response cleaning, validation, retries and failure accounting.

The validation is part of the measurement, not defensive programming. A refusal, a preamble or a
wholesale paraphrase each produce a large difference between chunk and rewrite, and none of them
means what a large difference is supposed to mean. Every pathological response named in
``docs/TESTING.md`` section 3 gets its own test here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mmlsa.chunking import Chunk
from mmlsa.distance.tokenize import load_function_words
from mmlsa.llm.base import LLMRequest, LLMResponse
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger
from mmlsa.llm.providers.fake import FakeProvider
from mmlsa.llm.runner import Runner
from mmlsa.pipeline.rewrite import (
    FailureReason,
    ValidationConfig,
    build_rewrite_request,
    clean_response,
    content_retention,
    report_creation,
    rewrite_chunks,
    strip_preamble,
    validate_rewrite,
)
from tests.conftest import REPO_ROOT

ORIGINAL = (
    "Thou hast the letter, and thou dost not read it. "
    "What dost thou fear that paper should declare? "
    "The hour is late; the candle burns to nothing; "
    "And yet thou standest as a man of stone."
)


@pytest.fixture(scope="module")
def function_words() -> frozenset[str]:
    """The shipped v1 list."""
    return frozenset(
        load_function_words(str(REPO_ROOT / "data" / "function_words" / "en_core_v1.txt"))
    )


def check(response: str, function_words: frozenset[str], original: str = ORIGINAL):
    """Validate a response against the original."""
    return validate_rewrite(original, response, function_words)


# ------------------------------------------------------------------- one per pathological case


def test_an_empty_response_is_rejected(function_words: frozenset[str]) -> None:
    """Nothing to measure."""
    assert check("", function_words).reason is FailureReason.EMPTY


def test_a_whitespace_only_response_is_rejected(function_words: frozenset[str]) -> None:
    """Distinct from empty at the byte level, identical in meaning."""
    assert check("   \n\n\t  ", function_words).reason is FailureReason.EMPTY


def test_a_response_that_is_only_a_fence_is_rejected(function_words: frozenset[str]) -> None:
    """Cleaning must not turn an empty fenced block into a passing empty string silently."""
    assert check("```\n```", function_words).reason is FailureReason.EMPTY


@pytest.mark.parametrize(
    "refusal",
    [
        "I cannot rewrite this passage.",
        "I'm sorry, but I can't help with that request.",
        "As an AI language model, I am unable to comply.",
        "I will not reproduce this text.",
    ],
)
def test_a_refusal_is_rejected(refusal: str, function_words: frozenset[str]) -> None:
    """A refusal is not a rewrite, and would otherwise be scored as an enormous style change."""
    assert check(refusal, function_words).reason is FailureReason.REFUSAL


def test_a_half_length_response_is_rejected(function_words: frozenset[str]) -> None:
    """Below the specified 0.60 ratio: the model summarized instead of rewriting."""
    half = " ".join(ORIGINAL.split()[: len(ORIGINAL.split()) // 2])
    outcome = check(half, function_words)

    assert outcome.reason is FailureReason.TOO_SHORT
    assert outcome.detail["length_ratio"] < 0.60


def test_a_double_length_response_is_rejected(function_words: frozenset[str]) -> None:
    """Above the specified 1.60 ratio: the model expanded or explained itself."""
    outcome = check(ORIGINAL + " " + ORIGINAL, function_words)

    assert outcome.reason is FailureReason.TOO_LONG
    assert outcome.detail["length_ratio"] > 1.60


def test_a_full_paraphrase_is_rejected(function_words: frozenset[str]) -> None:
    """The content words are gone, so this measures meaning change rather than style change.

    Same length and no refusal, so only the retention check can catch it. This is the case the
    method is most exposed to: a fluent, plausible response that destroys the measurement.
    """
    paraphrase = (
        "Thou keepest the message, and thou dost not open it. "
        "What dost thou dread that document might reveal? "
        "The evening grows old; the taper wastes away; "
        "And still thou waitest as a shape of rock."
    )
    outcome = check(paraphrase, function_words)

    assert outcome.reason is FailureReason.CONTENT_LOST
    assert outcome.detail["content_retention"] < 0.50


def test_an_unchanged_copy_of_the_input_is_accepted(function_words: frozenset[str]) -> None:
    """The case that is easy to get backwards.

    A rewrite identical to the original means the model found nothing to change, which is exactly
    what an authentic chunk should produce. Rejecting it would discard the strongest evidence the
    method can generate.
    """
    outcome = check(ORIGINAL, function_words)

    assert outcome.ok
    assert outcome.cleaned == ORIGINAL
    assert outcome.detail["content_retention"] == 1.0


def test_a_genuine_style_rewrite_is_accepted(function_words: frozenset[str]) -> None:
    """The normal case: function words change, content words do not."""
    rewritten = (
        "You have the letter, and you do not read it. "
        "What do you fear that paper should declare? "
        "The hour is late; the candle burns to nothing; "
        "And yet you stand as a man of stone."
    )
    outcome = check(rewritten, function_words)

    assert outcome.ok
    assert outcome.detail["content_retention"] >= 0.50


# ------------------------------------------------------------------------------------- cleaning


def test_a_chatty_preamble_is_stripped_and_the_rewrite_accepted(
    function_words: frozenset[str],
) -> None:
    """The preamble would otherwise be measured as part of the passage."""
    outcome = check(f"Here is the rewritten passage:\n{ORIGINAL}", function_words)

    assert outcome.ok
    assert outcome.cleaned == ORIGINAL


@pytest.mark.parametrize(
    "preamble",
    [
        "Here is the rewritten passage:",
        "Here's the passage, rewritten to match:",
        "Sure, here is your text:",
        "Certainly! The rewritten version:",
        "Rewritten passage:",
        "Below is the requested rewrite:",
    ],
)
def test_each_specified_preamble_form_is_stripped(preamble: str) -> None:
    """The exact pattern from docs/SPEC.md Step 3."""
    assert strip_preamble(f"{preamble}\n{ORIGINAL}") == ORIGINAL


def test_a_markdown_fence_is_stripped_and_the_rewrite_accepted(
    function_words: frozenset[str],
) -> None:
    """Models fence prose despite being asked not to."""
    outcome = check(f"```\n{ORIGINAL}\n```", function_words)

    assert outcome.ok
    assert outcome.cleaned == ORIGINAL


def test_a_fence_and_a_preamble_together_are_both_stripped(
    function_words: frozenset[str],
) -> None:
    """Fences come off first, or a preamble inside the fence would still be wrapped."""
    outcome = check(f"```text\nHere is the rewrite:\n{ORIGINAL}\n```", function_words)

    assert outcome.ok
    assert outcome.cleaned == ORIGINAL


def test_line_breaks_inside_the_passage_are_preserved() -> None:
    """Everything after the preamble is preserved verbatim, line breaks included."""
    passage = "First line.\nSecond line.\n\nAfter a blank."

    assert strip_preamble(f"Here is the rewrite:\n{passage}") == passage


def test_a_line_of_the_passage_is_not_mistaken_for_a_preamble() -> None:
    """The pattern requires a trailing colon and newline, so ordinary prose survives."""
    passage = "Here is the man I told you of, and he is late."

    assert strip_preamble(passage) == passage


def test_only_one_preamble_line_is_removed() -> None:
    """Peeling repeatedly would eventually start eating the passage itself."""
    doubled = f"Here is the rewrite:\nSure, here it is:\n{ORIGINAL}"

    assert strip_preamble(doubled) == f"Sure, here it is:\n{ORIGINAL}"


def test_cleaning_can_be_switched_off() -> None:
    """Both stripping steps are configuration, so the raw behaviour can be measured if needed."""
    raw = f"```\nHere is the rewrite:\n{ORIGINAL}\n```"
    off = ValidationConfig(strip_preamble=False, strip_code_fences=False)

    assert clean_response(raw, off) == raw.strip()


# ------------------------------------------------------------------------- content retention


def test_retention_is_one_when_content_words_are_unchanged(
    function_words: frozenset[str],
) -> None:
    """Changing only function words must not register as content loss."""
    modern = ORIGINAL.replace("Thou", "You").replace("thou", "you").replace("dost", "do")

    assert content_retention(ORIGINAL, modern, function_words) == 1.0


def test_retention_is_zero_when_no_content_word_survives(
    function_words: frozenset[str],
) -> None:
    """The bound the check exists to catch."""
    assert content_retention("cats sleep peacefully", "dogs bark loudly", function_words) == 0.0


def test_retention_uses_types_not_frequencies(function_words: frozenset[str]) -> None:
    """Frequencies are the style signal; requiring them to survive would forbid rewriting."""
    original = "letter letter letter candle"
    rewrite = "letter candle candle candle"

    assert content_retention(original, rewrite, function_words) == 1.0


def test_added_words_do_not_reduce_retention(function_words: frozenset[str]) -> None:
    """The overlap coefficient asks how much of the smaller vocabulary is shared."""
    assert content_retention("letter candle", "letter candle stone hour", function_words) == 1.0


def test_a_chunk_with_no_content_words_is_vacuously_retained(
    function_words: frozenset[str],
) -> None:
    """A passage of pure function words cannot lose content it never had."""
    assert content_retention("of the and to", "of thy and unto", function_words) == 1.0


# ------------------------------------------------------------------------------------- requests


def test_a_retry_is_the_same_prompt_with_a_clarification_appended() -> None:
    """Specified behaviour, and it makes the retry a separate cache entry by construction."""
    first = build_rewrite_request("a passage", "a profile")
    retry = build_rewrite_request("a passage", "a profile", retry=True)

    assert retry.prompt.startswith(first.prompt)
    assert "return only the rewritten passage" in retry.prompt
    assert retry.prompt_schema_version != first.prompt_schema_version


def test_a_rewrite_request_is_tagged_and_deterministic() -> None:
    """The tag drives the ledger; determinism drives the cache."""
    request = build_rewrite_request("a passage", "a profile")

    assert request.tag == "rewrite"
    assert request.temperature == 0.0
    assert request == build_rewrite_request("a passage", "a profile")


def test_the_profile_reaches_the_prompt_as_labelled_lines() -> None:
    """Never raw JSON: it changes the register of the instruction."""
    request = build_rewrite_request("a passage", "Vocabulary: plain\nPronouns: second person")

    assert "Vocabulary: plain" in request.prompt
    assert "a passage" in request.prompt


# ------------------------------------------------------------------------------- the worker


class ScriptedProvider:
    """Returns a scripted sequence of responses, then falls back to a real rewrite."""

    name = "fake"

    def __init__(self, script: list[str]) -> None:
        self._inner = FakeProvider()
        self.model_id = self._inner.model_id
        self._script = list(script)
        self.calls = 0

    def context_window(self) -> int:
        return self._inner.context_window()

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self._script:
            return LLMResponse(
                text=self._script.pop(0), model_id=self.model_id, model_version="scripted"
            )
        return self._inner.complete(request)


def make_runner(tmp_path: Path, provider=None) -> Runner:
    """A runner over the given provider."""
    return Runner(
        provider=provider or FakeProvider(),
        cache=ResponseCache(tmp_path / "cache"),
        ledger=Ledger(tmp_path / "runs" / "r1" / "calls.jsonl", run_id="r1"),
        concurrency=2,
    )


def chunks_from(text: str, creation_id: str = "text_a", size: int = 20) -> list[Chunk]:
    """Chunk a text for the worker."""
    from mmlsa.chunking import chunk_text

    return chunk_text(text, size, creation_id=creation_id)


def test_every_chunk_gets_a_rewrite(function_words: frozenset[str], tmp_path: Path) -> None:
    """The M7 acceptance criterion, against FakeProvider."""
    text = (REPO_ROOT / "tests" / "fixtures" / "mini_corpus" / "mini_alpha.txt").read_text(
        encoding="utf-8"
    )
    chunks = chunks_from(text, size=60)

    rewrites = rewrite_chunks(chunks, "Vocabulary: plain", make_runner(tmp_path), function_words)

    assert len(rewrites) == len(chunks)
    assert all(r.ok for r in rewrites)
    assert all(r.rewrite for r in rewrites)


def test_results_are_returned_in_chunk_order(
    function_words: frozenset[str], tmp_path: Path
) -> None:
    """Order must not depend on which worker finished first."""
    chunks = chunks_from(" ".join(f"word{i}" for i in range(200)), size=20)

    rewrites = rewrite_chunks(chunks, "Vocabulary: plain", make_runner(tmp_path), function_words)

    assert [r.chunk_index for r in rewrites] == [c.index for c in chunks]


def test_an_invalid_response_is_retried_and_can_then_succeed(
    function_words: frozenset[str], tmp_path: Path
) -> None:
    """A refusal on the first attempt, a real rewrite on the second."""
    provider = ScriptedProvider(["I cannot rewrite this passage."])
    chunks = chunks_from(ORIGINAL, size=100)

    rewrites = rewrite_chunks(
        chunks, "Vocabulary: plain", make_runner(tmp_path, provider), function_words, max_retries=2
    )

    assert rewrites[0].ok
    assert rewrites[0].attempts == 2


def test_a_chunk_that_never_validates_is_marked_failed(
    function_words: frozenset[str], tmp_path: Path
) -> None:
    """Excluded from the mean and counted, rather than scored as an enormous change."""
    provider = ScriptedProvider(["I cannot."] * 10)
    chunks = chunks_from(ORIGINAL, size=100)

    rewrites = rewrite_chunks(
        chunks, "Vocabulary: plain", make_runner(tmp_path, provider), function_words, max_retries=2
    )

    assert not rewrites[0].ok
    assert rewrites[0].reason is FailureReason.REFUSAL
    assert rewrites[0].attempts == 3


def test_retries_are_bounded(function_words: frozenset[str], tmp_path: Path) -> None:
    """``max_retries`` of zero means one attempt and no more."""
    provider = ScriptedProvider(["I cannot."] * 10)
    chunks = chunks_from(ORIGINAL, size=100)

    rewrites = rewrite_chunks(
        chunks, "Vocabulary: plain", make_runner(tmp_path, provider), function_words, max_retries=0
    )

    assert rewrites[0].attempts == 1
    assert provider.calls == 1


def test_one_bad_chunk_does_not_affect_its_neighbours(
    function_words: frozenset[str], tmp_path: Path
) -> None:
    """A run must not lose good work because one chunk is cursed."""
    provider = ScriptedProvider(["I cannot."] * 3)
    chunks = chunks_from(" ".join(f"word{i}" for i in range(200)), size=20)

    rewrites = rewrite_chunks(
        chunks, "Vocabulary: plain", make_runner(tmp_path, provider), function_words, max_retries=0
    )

    assert sum(1 for r in rewrites if r.ok) == len(chunks) - 3


# ---------------------------------------------------------------------------------- accounting


def test_the_report_counts_failures_by_kind(function_words: frozenset[str], tmp_path: Path) -> None:
    """Totals alone would not say whether the model is refusing or paraphrasing."""
    provider = ScriptedProvider(["I cannot.", "", "short"])
    chunks = chunks_from(" ".join(f"word{i}" for i in range(200)), size=20)

    rewrites = rewrite_chunks(
        chunks, "Vocabulary: plain", make_runner(tmp_path, provider), function_words, max_retries=0
    )
    report = report_creation("text_a", 1, rewrites)

    assert report.n_chunks == len(chunks)
    assert report.n_failed == 3
    assert report.reasons["refusal"] == 1
    assert report.reasons["empty"] == 1
    assert report.reasons["too_short"] == 1


def test_exceeding_the_failed_fraction_flags_the_creation_unreliable() -> None:
    """docs/SPEC.md Step 3: above the bound, the score is reported but marked."""
    from mmlsa.pipeline.rewrite import ChunkRewrite, RewriteStatus

    def made(index: int, ok: bool) -> ChunkRewrite:
        return ChunkRewrite(
            creation_id="text_a",
            chunk_index=index,
            original="x",
            rewrite="x" if ok else "",
            status=RewriteStatus.OK if ok else RewriteStatus.FAILED,
            attempts=1,
            n_words_original=1,
            n_words_rewrite=1 if ok else 0,
            reason=None if ok else FailureReason.EMPTY,
        )

    within = [made(i, ok=i > 0) for i in range(100)]
    beyond = [made(i, ok=i > 4) for i in range(100)]

    assert report_creation("text_a", 1, within, max_failed_fraction=0.02).unreliable is False
    assert report_creation("text_a", 1, beyond, max_failed_fraction=0.02).unreliable is True


def test_the_report_counts_retried_chunks(function_words: frozenset[str], tmp_path: Path) -> None:
    """A high retry count is a signal about the model, worth seeing before the failures start."""
    provider = ScriptedProvider(["I cannot."])
    chunks = chunks_from(" ".join(f"word{i}" for i in range(100)), size=20)

    rewrites = rewrite_chunks(
        chunks, "Vocabulary: plain", make_runner(tmp_path, provider), function_words, max_retries=2
    )
    report = report_creation("text_a", 1, rewrites)

    assert report.n_retried == 1
    assert report.n_failed == 0
