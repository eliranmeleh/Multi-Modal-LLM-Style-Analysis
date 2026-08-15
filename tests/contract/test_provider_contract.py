"""The contract every provider must satisfy.

Run against every implementation, so that swapping ``llm.provider`` cannot change the pipeline's
assumptions. When the live backends are wired at M9 they are added to the fixture below and must
pass this suite unchanged, offline, against recorded responses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mmlsa.llm.base import CacheMissError, LLMProvider, LLMRequest, LLMResponse
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.providers import UnknownProviderError, available, build_provider
from mmlsa.llm.providers.fake import FakeProvider


@pytest.fixture(params=["fake", "replay"])
def provider(request: pytest.FixtureRequest, tmp_path: Path) -> LLMProvider:
    """Each registered provider, primed so that ``complete`` can succeed."""
    cache = ResponseCache(tmp_path / "cache")

    if request.param == "replay":
        # Replay serves only what is recorded, so record the contract request first.
        seeded = ReplaySeed(cache)
        seeded.seed(CONTRACT_REQUEST)
        return build_provider("replay", cache=cache)

    return build_provider("fake")


CONTRACT_REQUEST = LLMRequest(
    prompt="Passage to rewrite:\nyou have your will and you do not know it",
    tag="rewrite",
    max_output_tokens=256,
)


class ReplaySeed:
    """Writes a recorded response so the replay provider has something to serve."""

    def __init__(self, cache: ResponseCache) -> None:
        self.cache = cache

    def seed(self, request: LLMRequest) -> LLMResponse:
        """Record a response for ``request`` under the replay provider's namespace."""
        response = LLMResponse(
            text="thou hast thy will and thou dost not know it",
            model_id="replay",
            model_version="replay-recorded",
            input_tokens=11,
            output_tokens=10,
            latency_ms=1,
        )
        key = ResponseCache.key_for("replay", "replay", request)
        self.cache.put(key, "replay", "replay", request, response)
        return response


# ------------------------------------------------------------------------------- the protocol


def test_provider_satisfies_the_protocol(provider: LLMProvider) -> None:
    """Structural conformance, so pipeline code can depend on the interface alone."""
    assert isinstance(provider, LLMProvider)
    assert isinstance(provider.name, str) and provider.name
    assert isinstance(provider.model_id, str) and provider.model_id


def test_context_window_is_a_positive_integer(provider: LLMProvider) -> None:
    """Step 1 packs whole creations against this number; a zero would divide by nothing."""
    window = provider.context_window()

    assert isinstance(window, int)
    assert window > 0


def test_complete_returns_a_populated_response(provider: LLMProvider) -> None:
    """Every field the ledger records must be present and of the right type."""
    response = provider.complete(CONTRACT_REQUEST)

    assert isinstance(response, LLMResponse)
    assert response.text.strip()
    assert response.model_id
    assert response.model_version
    assert isinstance(response.input_tokens, int)
    assert isinstance(response.output_tokens, int)
    assert isinstance(response.latency_ms, int)
    assert response.finish_reason
    assert isinstance(response.raw, dict)


def test_the_same_request_gives_the_same_response(provider: LLMProvider) -> None:
    """Determinism is required of every offline provider, and is what makes replay meaningful."""
    first = provider.complete(CONTRACT_REQUEST)
    second = provider.complete(CONTRACT_REQUEST)

    assert first.text == second.text


def test_a_response_round_trips_through_serialization(provider: LLMProvider) -> None:
    """The cache stores responses as JSON, so this has to be lossless."""
    response = provider.complete(CONTRACT_REQUEST)
    restored = LLMResponse.from_dict(response.to_dict())

    assert restored == response


# ------------------------------------------------------------------------- provider-specific


def test_the_fake_provider_does_not_echo_its_input() -> None:
    """A fake that echoes makes every delta zero and every downstream test vacuous."""
    fake = FakeProvider()
    passage = " ".join(["you have your will and you do not know it"] * 20)
    request = LLMRequest(prompt=f"Passage to rewrite:\n{passage}", tag="rewrite")

    rewritten = fake.complete(request).text

    assert rewritten != passage
    assert len(rewritten.split()) == len(passage.split())


def test_the_fake_provider_varies_its_rate_between_inputs() -> None:
    """A single fixed rate would give every creation the same score and no gap to threshold."""
    fake = FakeProvider()
    passage = " ".join(["you have your will and you do not know it"] * 10)

    changed_counts = set()
    for index in range(12):
        request = LLMRequest(
            prompt=f"Chunk {index}.\nPassage to rewrite:\n{passage}", tag="rewrite"
        )
        rewritten = fake.complete(request).text.split()
        changed_counts.add(
            sum(1 for a, b in zip(passage.split(), rewritten, strict=True) if a != b)
        )

    assert len(changed_counts) > 3, f"substitution counts barely varied: {sorted(changed_counts)}"


def test_the_fake_provider_returns_a_structured_profile_when_asked() -> None:
    """Step 1 needs the six documented keys; the fake supplies them so M6 can be built offline."""
    import json

    fake = FakeProvider()
    response = fake.complete(LLMRequest(prompt="Analyze the style.", tag="profile"))
    profile = json.loads(response.text)

    assert set(profile) == {
        "vocabulary",
        "pronouns",
        "verb_forms",
        "sentence_structure",
        "punctuation",
        "other",
    }
    assert all(isinstance(value, str) and value for value in profile.values())


def test_the_fake_provider_is_stable_across_processes() -> None:
    """Seeded from a sha256 of the prompt, not from Python's per-process salted hash."""
    request = LLMRequest(prompt="Passage to rewrite:\nyou do have your will", tag="rewrite")

    assert FakeProvider().complete(request).text == FakeProvider().complete(request).text


def test_the_replay_provider_refuses_an_unrecorded_request(tmp_path: Path) -> None:
    """The whole point: reproducing a published run either matches, or says it cannot."""
    provider = build_provider("replay", cache=ResponseCache(tmp_path / "cache"))

    with pytest.raises(CacheMissError, match="no recorded response"):
        provider.complete(LLMRequest(prompt="never recorded", tag="rewrite"))


# ------------------------------------------------------------------------------- the registry


def test_the_registry_exposes_the_offline_providers() -> None:
    """Both must be selectable by the single configuration key that chooses a provider."""
    assert available() == ["fake", "replay"]


def test_the_planned_backends_fail_with_the_milestone_that_delivers_them() -> None:
    """Better a message naming M9 than an import error deep in a run."""
    for name in ("gemini", "openai", "anthropic"):
        with pytest.raises(UnknownProviderError, match="M9"):
            build_provider(name)


def test_an_unknown_provider_lists_what_is_available() -> None:
    """A typo in the configuration should say what to type instead."""
    with pytest.raises(UnknownProviderError, match="Available"):
        build_provider("not_a_provider")


def test_the_replay_provider_cannot_be_built_without_a_cache() -> None:
    """It has nothing to serve otherwise, and would fail on the first call rather than at startup."""
    with pytest.raises(UnknownProviderError, match="requires a cache"):
        build_provider("replay")
