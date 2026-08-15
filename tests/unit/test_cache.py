"""The content-addressed cache.

``docs/DECISIONS.md`` I1 calls this the highest-leverage decision in the codebase. These tests are
what make that claim checkable: identity, the three modes, and stability across processes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmlsa.llm.base import CacheMissError, LLMRequest, LLMResponse
from mmlsa.llm.cache import ResponseCache

REQUEST = LLMRequest(prompt="rewrite this passage", tag="rewrite", max_output_tokens=512)
RESPONSE = LLMResponse(
    text="rewritten passage",
    model_id="fake-1",
    model_version="fake-1-deterministic",
    input_tokens=3,
    output_tokens=2,
    latency_ms=7,
)


@pytest.fixture
def cache(tmp_path: Path) -> ResponseCache:
    """An empty cache in live mode."""
    return ResponseCache(tmp_path / "cache")


def key(request: LLMRequest = REQUEST, provider: str = "fake", model: str = "fake-1") -> str:
    """The cache key for a request."""
    return ResponseCache.key_for(provider, model, request)


# ------------------------------------------------------------------------------------ identity


def test_the_key_is_a_sha256_hex_digest() -> None:
    """Fixed width and hex, because it becomes a path component."""
    digest = key()

    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)


def test_the_key_is_stable_across_processes_and_machines() -> None:
    """Canonical JSON over declared fields only: no timestamps, no paths, no dict ordering.

    If this were unstable, no two people could share a cache and no published run could be replayed
    by anyone else, which would remove the point of publishing it.
    """
    import subprocess
    import sys

    script = (
        "from mmlsa.llm.base import LLMRequest;"
        "from mmlsa.llm.cache import ResponseCache;"
        "print(ResponseCache.key_for('fake','fake-1',"
        "LLMRequest(prompt='rewrite this passage', tag='rewrite', max_output_tokens=512)))"
    )
    other_process = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )

    assert other_process.stdout.strip() == key()


@pytest.mark.parametrize(
    "changed",
    [
        {"prompt": "a different passage"},
        {"system": "a system instruction"},
        {"temperature": 0.7},
        {"max_output_tokens": 1024},
        {"response_format": "json"},
        {"prompt_schema_version": 2},
    ],
)
def test_changing_any_keyed_field_changes_the_key(changed: dict) -> None:
    """Every field that could change the answer must change the identity of the answer."""
    from dataclasses import replace

    assert key(replace(REQUEST, **changed)) != key()


def test_bumping_the_prompt_schema_version_invalidates_exactly_that_entry(
    cache: ResponseCache,
) -> None:
    """Editing a template must invalidate its entries and nothing else (docs/PROMPTS.md section 0)."""
    from dataclasses import replace

    cache.put(key(), "fake", "fake-1", REQUEST, RESPONSE)

    assert cache.get(key()) is not None
    assert cache.get(key(replace(REQUEST, prompt_schema_version=2))) is None


def test_the_tag_does_not_affect_the_key() -> None:
    """The tag labels what a call is for, not what was asked.

    Including it would mean the same prompt issued from two places paid twice for one answer.
    """
    from dataclasses import replace

    assert key(replace(REQUEST, tag="control")) == key()


def test_changing_the_provider_or_the_model_changes_the_key() -> None:
    """Two models do not give the same answer, so they must not share an entry."""
    assert key(provider="other") != key()
    assert key(model="fake-2") != key()


# ---------------------------------------------------------------------------- reading, writing


def test_a_miss_then_a_hit(cache: ResponseCache) -> None:
    """The core behaviour: write once, read forever."""
    assert cache.get(key()) is None
    assert cache.stats.misses == 1

    cache.put(key(), "fake", "fake-1", REQUEST, RESPONSE)
    restored = cache.get(key())

    assert restored == RESPONSE
    assert cache.stats.hits == 1
    assert cache.stats.writes == 1


def test_entries_are_sharded_by_the_first_two_characters(cache: ResponseCache) -> None:
    """Keeps directories small when several runs' worth of entries accumulate."""
    digest = key()
    path = cache.put(digest, "fake", "fake-1", REQUEST, RESPONSE)

    assert path.parent.name == digest[:2]
    assert path.name == f"{digest}.json"


def test_a_stored_entry_records_its_provenance(cache: ResponseCache) -> None:
    """The entry has to be interpretable on its own, months later, without the run that made it."""
    path = cache.put(key(), "fake", "fake-1", REQUEST, RESPONSE)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["key"] == key()
    assert payload["provider"] == "fake"
    assert payload["model_version"] == RESPONSE.model_version
    assert payload["request"]["prompt"] == REQUEST.prompt
    assert payload["response"]["text"] == RESPONSE.text
    assert payload["created_utc"].endswith("Z")


def test_a_corrupt_entry_is_a_miss_and_is_counted(cache: ResponseCache) -> None:
    """Refetching costs one call; returning a wrong answer would cost the whole result."""
    path = cache.put(key(), "fake", "fake-1", REQUEST, RESPONSE)
    path.write_text("{ this is not json", encoding="utf-8")

    assert cache.get(key()) is None
    assert cache.stats.corrupt == 1


def test_writing_is_atomic_and_leaves_no_debris(cache: ResponseCache) -> None:
    """An interrupted run must not leave a half-written response that later reads as valid."""
    cache.put(key(), "fake", "fake-1", REQUEST, RESPONSE)

    assert not list(cache.root.rglob("*.tmp"))
    assert cache.count() == 1


# ---------------------------------------------------------------------------------------- modes


def test_replay_mode_serves_hits_but_never_writes(tmp_path: Path) -> None:
    """Reproduction reads; it does not add."""
    live = ResponseCache(tmp_path / "cache")
    live.put(key(), "fake", "fake-1", REQUEST, RESPONSE)

    replay = ResponseCache(tmp_path / "cache", mode="replay")

    assert replay.get(key()) == RESPONSE
    with pytest.raises(CacheMissError, match="may not write"):
        replay.put(key(), "fake", "fake-1", REQUEST, RESPONSE)


def test_refresh_mode_ignores_existing_entries(tmp_path: Path) -> None:
    """A deliberate re-measurement must actually re-measure."""
    live = ResponseCache(tmp_path / "cache")
    live.put(key(), "fake", "fake-1", REQUEST, RESPONSE)

    refresh = ResponseCache(tmp_path / "cache", mode="refresh")

    assert refresh.get(key()) is None
    assert refresh.stats.misses == 1


def test_refresh_mode_overwrites(tmp_path: Path) -> None:
    """The new response replaces the old one at the same address."""
    from dataclasses import replace

    refresh = ResponseCache(tmp_path / "cache", mode="refresh")
    refresh.put(key(), "fake", "fake-1", REQUEST, RESPONSE)
    refresh.put(key(), "fake", "fake-1", REQUEST, replace(RESPONSE, text="a newer answer"))

    assert ResponseCache(tmp_path / "cache").get(key()).text == "a newer answer"
    assert refresh.count() == 1


def test_an_unknown_mode_is_rejected_at_construction(tmp_path: Path) -> None:
    """Fail at startup, not on the first call an hour in."""
    with pytest.raises(ValueError, match="unknown cache mode"):
        ResponseCache(tmp_path / "cache", mode="offline")


# ----------------------------------------------------------------------------------- reporting


def test_statistics_track_hits_misses_and_writes(cache: ResponseCache) -> None:
    """Reported at the end of a run so the cost of a re-run is visible."""
    cache.get(key())
    cache.put(key(), "fake", "fake-1", REQUEST, RESPONSE)
    cache.get(key())
    cache.get(key())

    assert cache.stats.misses == 1
    assert cache.stats.hits == 2
    assert cache.stats.lookups == 3
    assert cache.stats.hit_rate == pytest.approx(2 / 3)


def test_contains_does_not_disturb_the_counters(cache: ResponseCache) -> None:
    """Used for planning a dry run, where a lookup is not a real lookup."""
    cache.put(key(), "fake", "fake-1", REQUEST, RESPONSE)
    assert cache.contains(key())
    assert cache.stats.hits == 0
    assert cache.stats.misses == 0
