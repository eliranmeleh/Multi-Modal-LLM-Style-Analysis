"""The three live backends, exercised entirely offline.

No test may reach the network (R5), so each provider's SDK is replaced by a stub module registered in
``sys.modules``. The stub records what was sent and returns a canned response, which is exactly the
part worth testing: the adapter, not the vendor's client.

What these tests protect, in order of how expensive the mistake would be:

* **A key is never invented.** Without the environment variable the provider refuses to construct, so
  a test run cannot issue a billable request even if a stub were missing.
* **``temperature = 0`` is sent where it can be, and its absence is recorded where it cannot.** The
  specification pins it; several current models reject the parameter outright.
* **An empty completion is refused.** Scored as-is it would be the maximum possible distance, and the
  creation would look maximally suspicious for a reason unrelated to its author.
* **Transient and permanent failures are told apart.** The runner retries one and records the other,
  and getting it backwards either wastes an hour or abandons a run over a rate limit.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from mmlsa.llm.base import (
    LLMProvider,
    LLMRequest,
    PermanentProviderError,
    TransientProviderError,
)
from mmlsa.llm.providers import LIVE, available, build_provider
from mmlsa.llm.providers._live import LiveProvider
from mmlsa.llm.providers.anthropic import AnthropicProvider
from mmlsa.llm.providers.gemini import GeminiProvider
from mmlsa.llm.providers.openai import OpenAIProvider

REWRITE = LLMRequest(
    prompt="Passage to rewrite:\nyou have your will and you do not know it",
    tag="rewrite",
    max_output_tokens=256,
)
PROFILE = LLMRequest(prompt="Describe the style.", tag="profile", response_format="json")

FAKE_KEY = "not-a-real-key"


# ------------------------------------------------------------------------------- the stub SDKs


class Recorder:
    """Captures the keyword arguments of the one call each stub client makes."""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.sent: dict[str, Any] = {}
        self.client_options: dict[str, Any] = {}

    def __call__(self, **kwargs: Any) -> Any:
        self.sent = kwargs
        if self.error is not None:
            raise self.error
        return self.response


def _module(name: str, **attributes: Any) -> ModuleType:
    """A throwaway module object carrying the attributes a provider looks up."""
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def install_gemini(monkeypatch: pytest.MonkeyPatch, recorder: Recorder) -> None:
    """Register a stub ``google.genai`` and ``google.genai.types``."""

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            recorder.client_options = kwargs
            self.models = SimpleNamespace(generate_content=recorder)

    types_module = _module(
        "google.genai.types",
        GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        HttpOptions=lambda **kwargs: SimpleNamespace(**kwargs),
        HttpRetryOptions=lambda **kwargs: SimpleNamespace(**kwargs),
        ThinkingConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setitem(sys.modules, "google", _module("google"))
    monkeypatch.setitem(sys.modules, "google.genai", _module("google.genai", Client=Client))
    monkeypatch.setitem(sys.modules, "google.genai.types", types_module)
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)


def install_openai(monkeypatch: pytest.MonkeyPatch, recorder: Recorder) -> None:
    """Register a stub ``openai``."""

    class OpenAI:
        def __init__(self, **kwargs: Any) -> None:
            recorder.client_options = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=recorder))

    monkeypatch.setitem(sys.modules, "openai", _module("openai", OpenAI=OpenAI))
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)


def install_anthropic(monkeypatch: pytest.MonkeyPatch, recorder: Recorder) -> None:
    """Register a stub ``anthropic``."""

    class Anthropic:
        def __init__(self, **kwargs: Any) -> None:
            recorder.client_options = kwargs
            self.messages = SimpleNamespace(create=recorder)

    monkeypatch.setitem(sys.modules, "anthropic", _module("anthropic", Anthropic=Anthropic))
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)


def gemini_response(text: str = "thou hast thy will", finish: str = "STOP") -> SimpleNamespace:
    """A response shaped like the Gemini SDK's, including its enum-valued finish reason."""
    return SimpleNamespace(
        text=text,
        model_version="gemini-2.5-flash-002",
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=11, candidates_token_count=9, thoughts_token_count=0
        ),
        prompt_feedback=None,
    )


def openai_response(text: str = "thou hast thy will") -> SimpleNamespace:
    """A response shaped like the OpenAI SDK's."""
    return SimpleNamespace(
        model="gpt-4.1-mini-2025-04-14",
        system_fingerprint="fp_abc",
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop"),
        ],
        usage=SimpleNamespace(
            prompt_tokens=11,
            completion_tokens=9,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
    )


def anthropic_response(
    text: str = "thou hast thy will", stop_reason: str = "end_turn"
) -> SimpleNamespace:
    """A response shaped like the Anthropic SDK's: content is a list of blocks, not a string."""
    return SimpleNamespace(
        model="claude-opus-5",
        stop_reason=stop_reason,
        stop_details=None,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=11, output_tokens=9),
    )


# ------------------------------------------------------------------------------- the registry


def test_every_named_backend_is_registered() -> None:
    """The book names three live backends; all three must be selectable by the one config key."""
    assert available() == ["anthropic", "fake", "gemini", "openai", "replay"]
    assert set(LIVE) == {"anthropic", "gemini", "openai"}


@pytest.mark.parametrize("name", ["gemini", "openai", "anthropic"])
def test_a_live_provider_without_its_key_refuses_to_construct(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guardrail that keeps a test run from issuing a real request.

    ``tests/conftest.py`` removes the three key variables before every test, so this is the failure
    a stray live configuration produces: a clear message at construction, not a billed call.
    """
    recorder = Recorder()
    {"gemini": install_gemini, "openai": install_openai, "anthropic": install_anthropic}[name](
        monkeypatch, recorder
    )
    monkeypatch.delenv(f"{name.upper()}_API_KEY", raising=False)

    with pytest.raises(PermanentProviderError, match="_API_KEY"):
        build_provider(name)


@pytest.mark.parametrize("name", ["gemini", "openai", "anthropic"])
def test_a_missing_sdk_names_the_extra_that_installs_it(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An optional dependency should say ``pip install`` and not raise ``ModuleNotFoundError``."""
    monkeypatch.setenv(f"{name.upper()}_API_KEY", FAKE_KEY)
    for module in ("google.genai", "openai", "anthropic"):
        monkeypatch.setitem(sys.modules, module, None)

    with pytest.raises(PermanentProviderError, match="pip install"):
        build_provider(name)


# ------------------------------------------------------------------------------- the protocol


@pytest.mark.parametrize("name", ["gemini", "openai", "anthropic"])
def test_a_live_provider_satisfies_the_protocol(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Structural conformance, so pipeline code can depend on the interface alone."""
    responses = {
        "gemini": gemini_response(),
        "openai": openai_response(),
        "anthropic": anthropic_response(),
    }
    recorder = Recorder(response=responses[name])
    {"gemini": install_gemini, "openai": install_openai, "anthropic": install_anthropic}[name](
        monkeypatch, recorder
    )

    provider = build_provider(name)
    response = provider.complete(REWRITE)

    assert isinstance(provider, LLMProvider)
    assert provider.context_window() > 0
    assert response.text == "thou hast thy will"
    assert response.model_id == provider.model_id
    assert response.model_version, "the version the provider reported must be recorded (R2)"
    assert (response.input_tokens, response.output_tokens) == (11, 9)
    assert response.finish_reason
    assert response.raw["provider"] == name


@pytest.mark.parametrize("name", ["gemini", "openai", "anthropic"])
def test_an_empty_completion_is_refused_rather_than_scored(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty rewrite scores as the maximum possible distance. That must never reach the report."""
    responses = {
        "gemini": gemini_response(text="", finish="MAX_TOKENS"),
        "openai": openai_response(text=""),
        "anthropic": anthropic_response(text=""),
    }
    recorder = Recorder(response=responses[name])
    {"gemini": install_gemini, "openai": install_openai, "anthropic": install_anthropic}[name](
        monkeypatch, recorder
    )

    with pytest.raises(PermanentProviderError, match="no text"):
        build_provider(name).complete(REWRITE)


@pytest.mark.parametrize("name", ["gemini", "openai", "anthropic"])
def test_the_configured_timeout_reaches_the_client(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``llm.timeout_seconds`` is a real setting, not a decorative one."""
    recorder = Recorder(response=gemini_response())
    {"gemini": install_gemini, "openai": install_openai, "anthropic": install_anthropic}[name](
        monkeypatch, recorder
    )

    build_provider(name, timeout_seconds=42)

    if name == "gemini":
        assert recorder.client_options["http_options"].timeout == 42_000
    else:
        assert recorder.client_options["timeout"] == 42.0
        assert recorder.client_options["max_retries"] == 0


# ------------------------------------------------------------- the specified generation parameters


def test_gemini_sends_the_specified_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every current Gemini model accepts it, so the specified value goes on the wire."""
    recorder = Recorder(response=gemini_response())
    install_gemini(monkeypatch, recorder)

    response = build_provider("gemini").complete(REWRITE)

    assert recorder.sent["config"].temperature == 0.0
    assert response.raw["wire"]["temperature"] == 0.0
    assert "temperature_sent" not in response.raw["wire"]


def test_gemini_holds_reasoning_at_the_lowest_value_each_model_permits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reasoning tokens come out of the output budget, so a rewrite can be starved by them."""
    recorder = Recorder(response=gemini_response())
    install_gemini(monkeypatch, recorder)

    build_provider("gemini", model_id="gemini-2.5-flash").complete(REWRITE)
    assert recorder.sent["config"].thinking_config.thinking_budget == 0

    build_provider("gemini", model_id="gemini-2.5-pro").complete(REWRITE)
    assert recorder.sent["config"].thinking_config.thinking_budget == 128

    build_provider("gemini", model_id="gemini-2.0-flash").complete(REWRITE)
    assert not hasattr(recorder.sent["config"], "thinking_config")


def test_gemini_asks_for_json_when_the_request_does(monkeypatch: pytest.MonkeyPatch) -> None:
    """Step 1 asks for a structured profile; the provider should use the native mode for it."""
    recorder = Recorder(response=gemini_response(text='{"vocabulary": "plain"}'))
    install_gemini(monkeypatch, recorder)

    build_provider("gemini").complete(PROFILE)

    assert recorder.sent["config"].response_mime_type == "application/json"


def test_a_system_prompt_reaches_every_backend_in_its_own_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No pipeline template uses one today, but the request field exists and must not be dropped.

    The three SDKs carry it three different ways: a config field, a message with a ``system`` role,
    and a top-level parameter. Silently discarding it would be invisible until someone added a
    system prompt and wondered why it changed nothing.
    """
    request = LLMRequest(prompt="Rewrite this.", system="Answer in one line.", tag="rewrite")

    gemini = Recorder(response=gemini_response())
    install_gemini(monkeypatch, gemini)
    build_provider("gemini").complete(request)
    assert gemini.sent["config"].system_instruction == "Answer in one line."

    openai = Recorder(response=openai_response())
    install_openai(monkeypatch, openai)
    build_provider("openai").complete(request)
    assert openai.sent["messages"][0] == {"role": "system", "content": "Answer in one line."}

    anthropic = Recorder(response=anthropic_response())
    install_anthropic(monkeypatch, anthropic)
    build_provider("anthropic").complete(request)
    assert anthropic.sent["system"] == "Answer in one line."


def test_the_json_request_format_is_honoured_however_each_backend_expresses_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two have a native JSON mode. Anthropic has none usable here, and records that it relied on
    the prompt, so the ledger shows which contract actually applied."""
    openai = Recorder(response=openai_response(text='{"vocabulary": "plain"}'))
    install_openai(monkeypatch, openai)
    build_provider("openai").complete(PROFILE)
    assert openai.sent["response_format"] == {"type": "json_object"}

    anthropic = Recorder(response=anthropic_response(text='{"vocabulary": "plain"}'))
    install_anthropic(monkeypatch, anthropic)
    recorded = build_provider("anthropic").complete(PROFILE)
    assert "response_format" not in anthropic.sent
    assert recorded.raw["wire"]["json_mode"] == "prompt_only"


def test_gemini_reports_a_safety_block_rather_than_an_empty_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blocked response returns successfully with no text; it must not become a score."""
    blocked = gemini_response(text="", finish="")
    blocked.prompt_feedback = SimpleNamespace(block_reason=SimpleNamespace(name="SAFETY"))
    install_gemini(monkeypatch, Recorder(response=blocked))

    with pytest.raises(PermanentProviderError, match="blocked:SAFETY"):
        build_provider("gemini").complete(REWRITE)


def test_openai_omits_a_temperature_the_reasoning_models_reject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sending it would be a 400. The omission is recorded so the ledger is not misleading."""
    recorder = Recorder(response=openai_response())
    install_openai(monkeypatch, recorder)

    response = build_provider("openai", model_id="o4-mini").complete(REWRITE)

    assert "temperature" not in recorder.sent
    assert recorder.sent["reasoning_effort"] == "low"
    assert response.raw["wire"]["temperature_sent"] is False
    assert response.raw["wire"]["temperature_requested"] == 0.0


def test_openai_uses_the_parameter_that_counts_reasoning_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``max_tokens`` is deprecated and does not bound reasoning; ``max_completion_tokens`` does."""
    recorder = Recorder(response=openai_response())
    install_openai(monkeypatch, recorder)

    build_provider("openai").complete(REWRITE)

    assert recorder.sent["max_completion_tokens"] == 256
    assert "max_tokens" not in recorder.sent
    assert recorder.sent["temperature"] == 0.0


def test_anthropic_omits_the_temperature_the_current_models_reject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The specification pins ``temperature = 0`` and these models refuse the parameter entirely."""
    recorder = Recorder(response=anthropic_response())
    install_anthropic(monkeypatch, recorder)

    response = build_provider("anthropic", model_id="claude-opus-5").complete(REWRITE)

    assert "temperature" not in recorder.sent
    assert recorder.sent["thinking"] == {"type": "disabled"}
    assert response.raw["wire"]["temperature_sent"] is False


def test_anthropic_sends_the_temperature_to_a_model_that_accepts_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The older models take it, and there the specified value is transmitted as written."""
    recorder = Recorder(response=anthropic_response())
    install_anthropic(monkeypatch, recorder)

    build_provider("anthropic", model_id="claude-haiku-4-5").complete(REWRITE)

    assert recorder.sent["temperature"] == 0.0
    assert "thinking" not in recorder.sent


def test_anthropic_gives_headroom_to_a_model_that_always_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Where reasoning cannot be switched off it shares ``max_tokens`` with the answer."""
    recorder = Recorder(response=anthropic_response())
    install_anthropic(monkeypatch, recorder)

    build_provider("anthropic", model_id="claude-fable-5").complete(REWRITE)

    assert recorder.sent["max_tokens"] > REWRITE.max_output_tokens
    assert "thinking" not in recorder.sent


def test_anthropic_reads_text_from_the_content_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """The content is a list of blocks; a response led by another kind must not lose its text."""
    message = anthropic_response()
    message.content = [
        SimpleNamespace(type="thinking", thinking="..."),
        SimpleNamespace(type="text", text="thou hast thy will"),
    ]
    install_anthropic(monkeypatch, Recorder(response=message))

    assert build_provider("anthropic").complete(REWRITE).text == "thou hast thy will"


def test_anthropic_reports_a_refusal_as_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """A declined request is a successful HTTP response carrying no text."""
    refused = anthropic_response(text="", stop_reason="refusal")
    refused.content = []
    refused.stop_details = SimpleNamespace(category="cyber")
    install_anthropic(monkeypatch, Recorder(response=refused))

    with pytest.raises(PermanentProviderError, match="declined"):
        build_provider("anthropic").complete(REWRITE)


# ------------------------------------------------------------------------------ failure sorting


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, TransientProviderError),
        (408, TransientProviderError),
        (500, TransientProviderError),
        (529, TransientProviderError),
        (400, PermanentProviderError),
        (401, PermanentProviderError),
        (404, PermanentProviderError),
    ],
)
@pytest.mark.parametrize("name", ["gemini", "openai", "anthropic"])
def test_http_failures_are_sorted_by_status(
    name: str, status: int, expected: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retrying a 400 wastes an hour; abandoning a 429 abandons the run."""

    class SdkError(Exception):
        def __init__(self) -> None:
            super().__init__(f"status {status}")
            self.status_code = status
            self.code = status

    recorder = Recorder(error=SdkError())
    {"gemini": install_gemini, "openai": install_openai, "anthropic": install_anthropic}[name](
        monkeypatch, recorder
    )

    with pytest.raises(expected):
        build_provider(name).complete(REWRITE)


@pytest.mark.parametrize("name", ["gemini", "openai", "anthropic"])
def test_a_failure_that_never_reached_the_service_is_transient(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closed socket or a read timeout carries no status and is worth another attempt."""
    recorder = Recorder(error=ConnectionError("connection reset"))
    {"gemini": install_gemini, "openai": install_openai, "anthropic": install_anthropic}[name](
        monkeypatch, recorder
    )

    with pytest.raises(TransientProviderError, match="connection reset"):
        build_provider(name).complete(REWRITE)


# -------------------------------------------------------------------------------- the model table


@pytest.mark.parametrize(
    "provider", [GeminiProvider, OpenAIProvider, AnthropicProvider], ids=lambda p: p.name
)
def test_the_default_model_is_listed_in_the_table(provider: type[LiveProvider]) -> None:
    """A default whose capabilities are unknown would be a guess on every call."""
    assert provider.default_model_id in provider.models


@pytest.mark.parametrize(
    "provider", [GeminiProvider, OpenAIProvider, AnthropicProvider], ids=lambda p: p.name
)
def test_a_dated_snapshot_inherits_the_capabilities_of_its_alias(
    provider: type[LiveProvider],
) -> None:
    """Providers publish snapshots faster than a table can track; the longest prefix wins."""
    alias = provider.default_model_id

    assert provider.spec_for(f"{alias}-20260401") == provider.models[alias]


def test_the_longest_matching_prefix_wins_over_a_shorter_one() -> None:
    """``gemini-2.5-flash`` is a prefix of ``gemini-2.5-flash-lite``; the specific one must win."""
    assert (
        GeminiProvider.spec_for("gemini-2.5-flash-lite-preview")
        == GeminiProvider.models["gemini-2.5-flash-lite"]
    )


def test_an_unlisted_model_takes_conservative_defaults() -> None:
    """Unknown is not an error, but it must not be assumed to accept a temperature it may reject."""
    assert AnthropicProvider.spec_for("claude-something-new").accepts_temperature is False
    assert GeminiProvider.spec_for("gemini-99-flash").context_window > 0
