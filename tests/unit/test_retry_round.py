"""The content-validation retry round in the cache key: every retry is a real new call.

``docs/DECISIONS.md`` I33, issue #16. Round 1 differs from round 0 by the clarification appended to
its prompt, but every later round repeats round 1's prompt. Without the round in the key, round 2
was served round 1's failed answer from the cache, and ``max_retries: 2`` gave one real retry.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from mmlsa.llm.base import LLMRequest, LLMResponse
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger
from mmlsa.llm.providers.fake import FakeProvider
from mmlsa.llm.runner import Runner
from mmlsa.pipeline.rewrite import RewriteStatus, build_rewrite_request, rewrite_chunks

# Keys computed before the round existed (commit e057b8f). If one of these changes, the answers
# already cached for first attempts and first retries stop being found and have to be bought again.
GOLDEN_ROUND_0 = "9ec728b34619142fb2b64b2685c62c062d8c5579270c878811b7b5058e2d6f51"
GOLDEN_ROUND_1 = "551cad8509fa15ef32d6ec0b0e444a2586b58cb40e42e4c15742504997948c90"

MODEL = ("gemini", "gemini-3.1-flash-lite")
PASSAGE = (
    "I have of late, but wherefore I know not, lost all my mirth, forgone all custom of "
    "exercises; and indeed it goes so heavily with my disposition that this goodly frame seems "
    "to me a sterile promontory."
)
WORDS = frozenset({"of", "the", "and", "to", "me"})


class AlwaysTooShort(FakeProvider):
    """A model whose every rewrite is one word, so every round fails the length check."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        return dataclasses.replace(super().complete(request), text="Nothing.")


def runner_for(tmp_path: Path, provider: FakeProvider, run_id: str = "r1") -> Runner:
    """A runner on a cache under ``tmp_path`` that persists across calls in one test."""
    return Runner(
        provider=provider,
        cache=ResponseCache(tmp_path / "cache"),
        ledger=Ledger(tmp_path / "runs" / run_id / "calls.jsonl", run_id=run_id),
        concurrency=1,
    )


def chunks_of(text: str):
    """The passage as chunks, through the real chunker."""
    from mmlsa.chunking import chunk_text

    return chunk_text(text, 10, creation_id="text_a")


# ---------------------------------------------------------------------- the old keys are kept


def test_rounds_zero_and_one_keep_the_keys_they_had_before_the_field_existed() -> None:
    """First attempts and first retries already cached are still found."""
    first = build_rewrite_request("the passage", "the profile")
    retry = build_rewrite_request("the passage", "the profile", retry_round=1)

    assert ResponseCache.key_for(*MODEL, first) == GOLDEN_ROUND_0
    assert ResponseCache.key_for(*MODEL, retry) == GOLDEN_ROUND_1
    assert "retry_round" not in retry.cache_fields(*MODEL)


def test_later_rounds_repeat_the_prompt_but_get_keys_of_their_own() -> None:
    """Same question to the model, a different sample in the cache."""
    requests = [
        build_rewrite_request("the passage", "the profile", retry_round=r) for r in (1, 2, 3)
    ]

    assert len({request.prompt for request in requests}) == 1
    assert len({ResponseCache.key_for(*MODEL, request) for request in requests}) == 3


def test_a_retry_round_below_zero_is_refused() -> None:
    """Rounds count from 0, the first attempt."""
    with pytest.raises(ValueError, match="retry_round"):
        LLMRequest(prompt="x", retry_round=-1)


# ------------------------------------------------------------------- the behaviour that matters


def test_every_retry_round_reaches_the_provider(tmp_path: Path) -> None:
    """The bug in #16: round 2 was a cache hit on round 1's failed answer."""
    provider = AlwaysTooShort()
    chunks = chunks_of(PASSAGE)

    results = rewrite_chunks(
        chunks, "a profile", runner_for(tmp_path, provider), WORDS, max_retries=2
    )

    assert provider.calls == 3 * len(chunks)
    assert all(result.status is RewriteStatus.FAILED for result in results)
    assert all(result.attempts == 3 for result in results)


def test_the_cache_entry_records_the_round_from_two_on(tmp_path: Path) -> None:
    """R7: a stored answer from a later retry says which round it was."""
    chunks = chunks_of(PASSAGE)

    rewrite_chunks(
        chunks, "a profile", runner_for(tmp_path, AlwaysTooShort()), WORDS, max_retries=2
    )

    entries = [
        json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "cache").rglob("*.json")
    ]
    rounds = [entry["request"].get("retry_round") for entry in entries]
    assert len(entries) == 3 * len(chunks)
    assert rounds.count(2) == len(chunks)
    assert rounds.count(None) == 2 * len(chunks)


def test_rerunning_a_run_with_retries_is_served_from_the_cache(tmp_path: Path) -> None:
    """R3 still holds: repeating the same run makes no call, retries included."""
    provider = AlwaysTooShort()
    chunks = chunks_of(PASSAGE)

    rewrite_chunks(chunks, "a profile", runner_for(tmp_path, provider), WORDS, max_retries=2)
    paid = provider.calls
    again = runner_for(tmp_path, provider, run_id="r2")
    rewrite_chunks(chunks, "a profile", again, WORDS, max_retries=2)

    assert provider.calls == paid
    assert again.stats.live == 0
    assert again.stats.cached == 3 * len(chunks)
