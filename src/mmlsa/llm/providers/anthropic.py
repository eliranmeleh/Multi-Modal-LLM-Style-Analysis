"""The Anthropic backend, through the ``anthropic`` SDK's messages endpoint.

The third of the three backends named in the approved book. Requires ``ANTHROPIC_API_KEY`` and the
``anthropic`` extra.

Three model behaviours shape this adapter, and all three are why the model table is not decoration.

*The current models reject ``temperature``.* Not ignore it: reject it, with a 400. ``docs/SPEC.md``
Step 3 pins ``temperature = 0``, so on those models the specified value cannot be transmitted at all
and sampling is left at the provider's own default. The request is still made, and the omission is
recorded per call so that a reader of ``calls.jsonl`` is never misled about it
(``docs/OPEN_QUESTIONS.md`` Q14).

*Reasoning is charged against ``max_tokens``, which is a ceiling on reasoning plus answer together.*
On the newest models reasoning is on unless switched off, so a rewrite call could spend its whole
budget deliberating and return nothing. It is switched off where the model allows that, and where it
cannot be switched off the wire budget is raised by a fixed headroom so the answer still has room.

*A refusal is a successful HTTP response.* The safety classifiers return 200 with
``stop_reason == "refusal"`` and an empty content list. Read naively that is an empty rewrite, which
scores as the maximum possible distance. It is raised here as a permanent failure naming the
category, so it is recorded as a refusal and the chunk is marked failed.

**Absolute imports.** This module is ``mmlsa.llm.providers.anthropic`` and imports the unrelated
top-level ``anthropic`` package. Python 3 resolves ``import anthropic`` absolutely, so the two do not
collide, but it is why the import goes through :func:`~mmlsa.llm.providers._live.load_sdk` by name.

See ``docs/ARCHITECTURE.md`` section 3.1.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mmlsa.llm.base import (
    LLMRequest,
    PermanentProviderError,
    ProviderError,
    TransientProviderError,
)
from mmlsa.llm.providers._live import Completion, LiveProvider, ModelSpec

CONTEXT_1M = 1_000_000

REASONING_HEADROOM_TOKENS = 4_096
"""Extra wire budget for models whose reasoning cannot be switched off.

``max_tokens`` bounds reasoning and answer together, so without headroom a model that always thinks
can exhaust the budget before writing anything. The headroom is a deterministic function of the model
identifier, which is itself part of the cache key, so it cannot make two runs of the same
configuration differ."""


class AnthropicProvider(LiveProvider):
    """One request, one response, through ``client.messages.create``."""

    name = "anthropic"
    env_var = "ANTHROPIC_API_KEY"
    extra = "anthropic"
    sdk_module = "anthropic"
    default_model_id = "claude-opus-5"
    """The current default model. It is also the most expensive of the candidates, so name a model
    explicitly in the configuration before running anything wide."""

    models: ClassVar[dict[str, ModelSpec]] = {
        "claude-opus-5": ModelSpec(CONTEXT_1M, accepts_temperature=False, reasoning="disable"),
        "claude-opus-4-8": ModelSpec(CONTEXT_1M, accepts_temperature=False, reasoning="disable"),
        "claude-opus-4-7": ModelSpec(CONTEXT_1M, accepts_temperature=False, reasoning="disable"),
        "claude-opus-4-6": ModelSpec(CONTEXT_1M, reasoning="disable"),
        "claude-sonnet-5": ModelSpec(CONTEXT_1M, accepts_temperature=False, reasoning="disable"),
        "claude-sonnet-4-6": ModelSpec(CONTEXT_1M, reasoning="disable"),
        "claude-haiku-4-5": ModelSpec(200_000),
        "claude-fable-5": ModelSpec(CONTEXT_1M, accepts_temperature=False, reasoning="always_on"),
    }
    unknown_model: ClassVar[ModelSpec] = ModelSpec(200_000, accepts_temperature=False)
    """An unlisted model is assumed to be a recent one, and the recent ones reject ``temperature``.
    Guessing the other way would turn every call into a 400."""

    def _connect(self, api_key: str) -> Any:
        """Build a client with the configured timeout and the SDK's own retries switched off."""
        return self._sdk.Anthropic(
            api_key=api_key, timeout=float(self.timeout_seconds), max_retries=0
        )

    def _invoke(self, request: LLMRequest) -> Completion:
        """Issue the call and reduce the response."""
        max_tokens = request.max_output_tokens
        if self.spec.reasoning == "always_on":
            max_tokens += REASONING_HEADROOM_TOKENS

        sent: dict[str, Any] = {"max_tokens": max_tokens}
        settings: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
        }

        if request.system:
            settings["system"] = request.system

        if self.send_temperature():
            settings["temperature"] = request.temperature
            sent["temperature"] = request.temperature

        if self.spec.reasoning == "disable":
            settings["thinking"] = {"type": "disabled"}
            sent["thinking"] = "disabled"
        elif self.spec.reasoning == "always_on":
            # An explicit setting is refused on these models; the parameter must simply be absent.
            sent["thinking"] = "always_on"
            sent["reasoning_headroom_tokens"] = REASONING_HEADROOM_TOKENS

        if request.response_format == "json":
            # No schema is available at this layer, so the JSON contract is the prompt's alone. The
            # profile parser tolerates a fenced or prose-wrapped object for exactly this reason.
            sent["json_mode"] = "prompt_only"

        message = self._client.messages.create(**settings)

        stop_reason = str(getattr(message, "stop_reason", None) or "stop")
        usage = getattr(message, "usage", None)

        if stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) or "unspecified"
            raise PermanentProviderError(
                f"anthropic declined this request (category '{category}'). The response carries no "
                "text, so there is nothing to score; the unit of work is recorded as failed."
            )

        return Completion(
            text=_text_of(message),
            model_version=str(getattr(message, "model", "") or ""),
            input_tokens=int(getattr(usage, "input_tokens", None) or 0),
            output_tokens=int(getattr(usage, "output_tokens", None) or 0),
            finish_reason=stop_reason,
            raw={"wire": self.wire_record(sent, request)},
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


def _text_of(message: Any) -> str:
    """Join the text blocks of a message, ignoring any other block type.

    The content is a list of blocks, not a string. Reading ``content[0].text`` unconditionally breaks
    the moment a response leads with a block of another kind.
    """
    parts = [
        str(getattr(block, "text", "") or "")
        for block in getattr(message, "content", None) or []
        if getattr(block, "type", "") == "text"
    ]
    return "".join(parts)
