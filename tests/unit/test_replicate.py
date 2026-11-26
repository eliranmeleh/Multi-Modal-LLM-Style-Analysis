"""The replicate index in the cache key: each of the `M` runs gets its own answers.

``docs/DECISIONS.md`` I32. Without the index, run 2 on identical inputs would be served run 1's
cached answer, and the run-to-run variance that Stage 2a measures would be zero by construction.
With it, run 1 must still hash exactly as before, so answers already paid for are still found.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmlsa.llm.base import LLMRequest
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger
from mmlsa.llm.providers.fake import FakeProvider
from mmlsa.llm.runner import Runner
from mmlsa.pipeline.profile import build_extraction_request, build_merge_request, extract_profile
from mmlsa.pipeline.rewrite import build_rewrite_request, rewrite_chunks

# Keys computed before the replicate field existed (commit 15513b3). If one of these changes, every
# cached answer from M9 and the Colab notebook stops being found and has to be bought again.
GOLDEN_PLAIN = "2812aba2c78d4e86be6e3dbefd1b0c3db75c4b3dd430f66d3655710a6ee34642"
GOLDEN_REWRITE = "9ec728b34619142fb2b64b2685c62c062d8c5579270c878811b7b5058e2d6f51"
GOLDEN_EXTRACT = "5885e16cc0f23230c4648c0af086b5b0556cb99f61521c9f7dae3e9c28da19c2"

MODEL = ("gemini", "gemini-3.1-flash-lite")
PASSAGE = (
    "I have of late, but wherefore I know not, lost all my mirth, forgone all custom of "
    "exercises; and indeed it goes so heavily with my disposition that this goodly frame seems "
    "to me a sterile promontory."
)
TEXTS = {"text_a": PASSAGE, "text_b": PASSAGE.upper()}


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


# ------------------------------------------------------------------------- run 1 keys unchanged


def test_replicate_one_keeps_the_key_it_had_before_the_field_existed() -> None:
    """Old cache entries still hit: run 1 hashes byte for byte as it always did."""
    plain = LLMRequest(prompt="rewrite this passage", tag="rewrite", max_output_tokens=512)

    assert ResponseCache.key_for("fake", "fake-1", plain) == GOLDEN_PLAIN
    assert ResponseCache.key_for(*MODEL, build_rewrite_request("the passage", "the profile")) == (
        GOLDEN_REWRITE
    )
    assert ResponseCache.key_for(
        *MODEL, build_extraction_request([("text_a", "some words here")])
    ) == (GOLDEN_EXTRACT)


def test_replicate_one_is_not_written_into_the_hashed_fields() -> None:
    """Absent rather than present with value 1, which is what keeps the old keys."""
    request = build_rewrite_request("the passage", "the profile", replicate=1)

    assert "replicate" not in request.cache_fields(*MODEL)


# ---------------------------------------------------------------------- later runs get new keys


@pytest.mark.parametrize("builder", ["rewrite", "extract", "merge"])
def test_every_later_replicate_has_its_own_key(builder: str) -> None:
    """Rewrites, profile extraction and the merge call all carry the run index."""
    from mmlsa.pipeline.profile import StyleProfile

    def build(replicate: int) -> LLMRequest:
        if builder == "rewrite":
            return build_rewrite_request("the passage", "the profile", replicate=replicate)
        if builder == "extract":
            return build_extraction_request([("text_a", "words")], replicate=replicate)
        partial = StyleProfile(fields={"vocabulary": "plain"}, structured=True)
        return build_merge_request([partial, partial], replicate=replicate)

    keys = {ResponseCache.key_for(*MODEL, build(r)) for r in (1, 2, 3)}

    assert len(keys) == 3


def test_the_replicate_does_not_change_what_the_model_is_asked() -> None:
    """Same prompt, same parameters: only the identity of the sample differs."""
    first = build_rewrite_request("the passage", "the profile", replicate=1)
    second = build_rewrite_request("the passage", "the profile", replicate=2)

    assert first.prompt == second.prompt
    assert first.temperature == second.temperature
    assert first.prompt_schema_version == second.prompt_schema_version


def test_a_replicate_below_one_is_refused() -> None:
    """Run indices count from 1; a zero would silently alias some other run."""
    with pytest.raises(ValueError, match="replicate"):
        LLMRequest(prompt="x", replicate=0)


def test_the_cache_entry_records_the_replicate(tmp_path: Path) -> None:
    """R7: a stored answer says which run's sample it is."""
    provider = FakeProvider()
    runner = runner_for(tmp_path, provider)

    rewrite_chunks(chunks_of(PASSAGE), "a profile", runner, frozenset({"of", "the"}), run_index=2)

    entries = [
        json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "cache").rglob("*.json")
    ]
    assert entries
    assert all(entry["request"]["replicate"] == 2 for entry in entries)


# ------------------------------------------------------------------- the behaviour that matters


def test_run_two_on_identical_input_calls_the_provider_again(tmp_path: Path) -> None:
    """The bug this fixes: run 2 used to be served run 1's answers, a cache hit on every chunk."""
    provider = FakeProvider()
    runner = runner_for(tmp_path, provider)
    chunks = chunks_of(PASSAGE)
    words = frozenset({"of", "the", "and", "to", "me"})

    rewrite_chunks(chunks, "a profile", runner, words, run_index=1)
    after_run_one = provider.calls
    rewrite_chunks(chunks, "a profile", runner, words, run_index=2)

    assert after_run_one == len(chunks)
    assert provider.calls == 2 * len(chunks)


def test_rerunning_the_same_run_is_served_from_the_cache(tmp_path: Path) -> None:
    """R3 still holds: a resumed or repeated run of the same index costs nothing."""
    provider = FakeProvider()
    chunks = chunks_of(PASSAGE)
    words = frozenset({"of", "the", "and", "to", "me"})

    for run_index in (1, 2):
        rewrite_chunks(
            chunks, "a profile", runner_for(tmp_path, provider), words, run_index=run_index
        )
    paid = provider.calls

    again = runner_for(tmp_path, provider, run_id="r2")
    for run_index in (1, 2):
        rewrite_chunks(chunks, "a profile", again, words, run_index=run_index)

    assert provider.calls == paid
    assert again.stats.live == 0
    assert again.stats.cached == 2 * len(chunks)


def test_profile_extraction_is_sampled_afresh_in_each_run(tmp_path: Path) -> None:
    """A run without noise extracts its own profile, rather than reusing run 1's."""
    provider = FakeProvider()
    runner = runner_for(tmp_path, provider)

    extract_profile(TEXTS, runner, run_index=1)
    after_run_one = provider.calls
    extract_profile(TEXTS, runner, run_index=2)
    extract_profile(TEXTS, runner, run_index=2)

    assert after_run_one >= 1
    assert provider.calls == 2 * after_run_one
