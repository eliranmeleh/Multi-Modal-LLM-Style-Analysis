"""Replaying a live provider's recorded answers needs no key and no SDK.

A peer examiner, or CI, reproduces a published run from its cache under ``llm.mode: replay``. Nothing
is sent in that mode, so building the live client, which reads the key, would only stop someone who
has every answer they need.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mmlsa.llm.base import CacheMissError, LLMRequest, LLMResponse, PermanentProviderError
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger
from mmlsa.llm.providers import (
    LIVE,
    build_provider,
    declared_context_window,
    default_model,
)
from mmlsa.llm.runner import Runner

REQUEST = LLMRequest(prompt="rewrite this passage", tag="rewrite", max_output_tokens=512)
MODEL = "gemini-3.1-flash-lite"


def recorded(tmp_path: Path, provider: str = "gemini", model: str = MODEL) -> ResponseCache:
    """A cache holding one answer, recorded under a live provider's name."""
    cache = ResponseCache(tmp_path / "cache")
    response = LLMResponse(
        text="the recorded rewrite",
        model_id=model,
        model_version=f"{model}-001",
        input_tokens=3,
        output_tokens=3,
        latency_ms=900,
    )
    cache.put(ResponseCache.key_for(provider, model, REQUEST), provider, model, REQUEST, response)
    return cache


def test_a_live_provider_still_needs_its_key_outside_replay(tmp_path: Path) -> None:
    # Without the SDK the refusal comes first; with it, the missing key. Either way, nothing is built.
    with pytest.raises(PermanentProviderError, match=r"GEMINI_API_KEY|mmlsa\[gemini\]"):
        build_provider("gemini", model_id=MODEL, cache=recorded(tmp_path))


@pytest.mark.parametrize("name", LIVE)
def test_replay_builds_every_live_provider_without_a_key(tmp_path: Path, name: str) -> None:
    provider = build_provider(name, cache=ResponseCache(tmp_path / "c"), mode="replay")
    assert provider.name == name
    assert provider.model_id == default_model(name)
    assert provider.context_window() == declared_context_window(name)


def test_replay_serves_the_recorded_answer_under_the_live_key(tmp_path: Path) -> None:
    cache = recorded(tmp_path)
    provider = build_provider("gemini", model_id=MODEL, cache=cache, mode="replay")
    runner = Runner(provider, cache, Ledger(tmp_path / "calls.jsonl", run_id="r"), mode="replay")

    result = runner.complete(REQUEST)

    assert result.cached
    assert result.response is not None
    assert result.response.text == "the recorded rewrite"


def test_replay_refuses_what_was_never_recorded(tmp_path: Path) -> None:
    cache = recorded(tmp_path, model="another-model")
    provider = build_provider("gemini", model_id=MODEL, cache=cache, mode="replay")
    runner = Runner(provider, cache, Ledger(tmp_path / "calls.jsonl", run_id="r"), mode="replay")

    with pytest.raises(CacheMissError):
        runner.complete(REQUEST)


def test_replay_still_needs_a_cache() -> None:
    with pytest.raises(Exception, match="cache"):
        build_provider("gemini", mode="replay")
