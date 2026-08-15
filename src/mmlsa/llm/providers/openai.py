"""The OpenAI backend, through the ``openai`` SDK's chat completions endpoint.

The second of the three backends named in the approved book. Requires ``OPENAI_API_KEY`` and the
``openai`` extra.

Chat completions rather than the newer responses endpoint, because this project needs one turn, one
prompt, one string back, and the older endpoint is the one every candidate model in the comparison
supports. ``max_completion_tokens`` is used rather than the deprecated ``max_tokens``: it is accepted
by every current model and it counts reasoning tokens, which the older parameter does not.

The reasoning families reject a temperature they do not intend to honour, so the specified
``temperature = 0`` cannot be sent to them at all. They are identified by name prefix and the
omission is recorded per call; see ``docs/OPEN_QUESTIONS.md`` Q14.

**Absolute imports.** This module is ``mmlsa.llm.providers.openai`` and imports the unrelated
top-level ``openai`` package. That works because Python 3 resolves ``import openai`` absolutely, but
it is why the import happens by name through :func:`~mmlsa.llm.providers._live.load_sdk` rather than
as a module-level statement.

See ``docs/ARCHITECTURE.md`` section 3.1.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mmlsa.llm.base import LLMRequest, ProviderError, TransientProviderError
from mmlsa.llm.providers._live import Completion, LiveProvider, ModelSpec

CONTEXT_1M = 1_047_576

REASONING_EFFORT = "low"
"""The rewrite task is a faithful restatement, not a problem to be solved. Reasoning tokens are
charged against ``max_completion_tokens``, so deliberation here buys nothing and can starve the
answer entirely."""


class OpenAIProvider(LiveProvider):
    """One request, one response, through ``client.chat.completions.create``."""

    name = "openai"
    env_var = "OPENAI_API_KEY"
    extra = "openai"
    sdk_module = "openai"
    default_model_id = "gpt-4.1-mini"

    # Context windows are stated conservatively. Understating one costs an extra profile call;
    # overstating it makes the request fail outright, so where a figure is uncertain the smaller
    # number is the safe one.
    models: ClassVar[dict[str, ModelSpec]] = {
        "gpt-4.1": ModelSpec(CONTEXT_1M),
        "gpt-4.1-mini": ModelSpec(CONTEXT_1M),
        "gpt-4.1-nano": ModelSpec(CONTEXT_1M),
        "gpt-4o": ModelSpec(128_000),
        "gpt-4o-mini": ModelSpec(128_000),
        "gpt-5": ModelSpec(200_000, accepts_temperature=False, reasoning="minimum"),
        "o1": ModelSpec(200_000, accepts_temperature=False, reasoning="minimum"),
        "o3": ModelSpec(200_000, accepts_temperature=False, reasoning="minimum"),
        "o4-mini": ModelSpec(200_000, accepts_temperature=False, reasoning="minimum"),
    }
    unknown_model: ClassVar[ModelSpec] = ModelSpec(128_000)

    def _connect(self, api_key: str) -> Any:
        """Build a client with the configured timeout and the SDK's own retries switched off."""
        return self._sdk.OpenAI(api_key=api_key, timeout=float(self.timeout_seconds), max_retries=0)

    def _invoke(self, request: LLMRequest) -> Completion:
        """Issue the call and reduce the response."""
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        sent: dict[str, Any] = {"max_completion_tokens": request.max_output_tokens}
        settings: dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "max_completion_tokens": request.max_output_tokens,
        }

        if self.send_temperature():
            settings["temperature"] = request.temperature
            sent["temperature"] = request.temperature

        if request.response_format == "json":
            settings["response_format"] = {"type": "json_object"}
            sent["response_format"] = "json_object"

        if self.spec.reasoning == "minimum":
            settings["reasoning_effort"] = REASONING_EFFORT
            sent["reasoning_effort"] = REASONING_EFFORT

        completion = self._client.chat.completions.create(**settings)

        choice = (getattr(completion, "choices", None) or [None])[0]
        usage = getattr(completion, "usage", None)
        details = getattr(usage, "completion_tokens_details", None)

        return Completion(
            text=getattr(getattr(choice, "message", None), "content", None) or "",
            model_version=getattr(completion, "model", "") or "",
            input_tokens=int(getattr(usage, "prompt_tokens", None) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", None) or 0),
            finish_reason=str(getattr(choice, "finish_reason", None) or "stop"),
            raw={
                "wire": self.wire_record(sent, request),
                "system_fingerprint": getattr(completion, "system_fingerprint", "") or "",
                "reasoning_tokens": int(getattr(details, "reasoning_tokens", None) or 0),
            },
        )

    def _translate(self, exc: Exception) -> ProviderError:
        """Sort an SDK exception by its HTTP status.

        ``APIConnectionError`` and ``APITimeoutError`` carry no status: nothing reached the service,
        which is exactly the case worth another attempt.
        """
        status = getattr(exc, "status_code", None)
        message = f"{type(exc).__name__}: {exc}"

        if isinstance(status, int):
            return self.classify_status(status, message)
        return TransientProviderError(message)
