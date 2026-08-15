"""The Gemini backend, through the ``google-genai`` SDK.

Named first in the approved book, and the default here for a practical reason: it has a free tier, so
the proof of concept can be run before anyone has spent anything. Requires ``GEMINI_API_KEY`` and the
``gemini`` extra.

Two things about this backend need care.

*Reasoning tokens are charged against the output budget.* The 2.5 series thinks before it answers,
and those tokens come out of ``max_output_tokens``. A rewrite call with a 2,048-token budget can
therefore spend the lot on reasoning and return an empty string, which
:class:`~mmlsa.llm.providers._live.LiveProvider` refuses rather than scores. The rewrite task does not
want deliberation anyway - it wants a faithful restatement - so reasoning is held at the lowest value
each model permits, and what was requested is recorded in the ledger.

*A blocked response still returns successfully.* Safety filtering produces a response object with no
candidate text and a ``block_reason``. That is reported here as a permanent failure naming the
reason, so it appears in ``calls.jsonl`` as a refusal rather than as a very short rewrite.

See ``docs/ARCHITECTURE.md`` section 3.1.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mmlsa.llm.base import LLMRequest, ProviderError, TransientProviderError
from mmlsa.llm.providers._live import Completion, LiveProvider, ModelSpec, load_sdk

CONTEXT_1M = 1_048_576


class GeminiProvider(LiveProvider):
    """One request, one response, through ``client.models.generate_content``."""

    name = "gemini"
    env_var = "GEMINI_API_KEY"
    extra = "gemini"
    sdk_module = "google.genai"
    default_model_id = "gemini-2.5-flash"

    models: ClassVar[dict[str, ModelSpec]] = {
        "gemini-2.5-pro": ModelSpec(CONTEXT_1M, reasoning="minimum", min_reasoning_tokens=128),
        "gemini-2.5-flash": ModelSpec(CONTEXT_1M, reasoning="disable"),
        "gemini-2.5-flash-lite": ModelSpec(CONTEXT_1M, reasoning="disable"),
        "gemini-2.0-flash": ModelSpec(CONTEXT_1M),
        "gemini-2.0-flash-lite": ModelSpec(CONTEXT_1M),
    }
    unknown_model: ClassVar[ModelSpec] = ModelSpec(CONTEXT_1M)

    def _connect(self, api_key: str) -> Any:
        """Build a client with the configured timeout and the SDK's own retries switched off."""
        self._types = load_sdk("google.genai.types", self.extra, self.name)
        genai = self._sdk

        options: dict[str, Any] = {"timeout": self.timeout_seconds * 1000}
        retry_options = getattr(self._types, "HttpRetryOptions", None)
        if retry_options is not None:
            # Retrying is the runner's job (docs/ARCHITECTURE.md section 5). Older releases of the
            # SDK do not expose this, in which case its default retries sit under ours.
            options["retry_options"] = retry_options(attempts=1)

        return genai.Client(api_key=api_key, http_options=self._types.HttpOptions(**options))

    def _generation_config(self, request: LLMRequest) -> tuple[Any, dict[str, Any]]:
        """Assemble the request configuration, and the record of it for the ledger."""
        sent: dict[str, Any] = {"max_output_tokens": request.max_output_tokens}
        settings: dict[str, Any] = {"max_output_tokens": request.max_output_tokens}

        if request.system:
            settings["system_instruction"] = request.system

        if self.send_temperature():
            settings["temperature"] = request.temperature
            sent["temperature"] = request.temperature

        if request.response_format == "json":
            settings["response_mime_type"] = "application/json"
            sent["response_mime_type"] = "application/json"

        budget = self._reasoning_budget()
        if budget is not None:
            settings["thinking_config"] = self._types.ThinkingConfig(thinking_budget=budget)
            sent["thinking_budget"] = budget

        return self._types.GenerateContentConfig(**settings), sent

    def _reasoning_budget(self) -> int | None:
        """The lowest reasoning budget this model accepts, or ``None`` if it has no such setting."""
        if self.spec.reasoning == "disable":
            return 0
        if self.spec.reasoning == "minimum":
            return self.spec.min_reasoning_tokens
        return None

    def _invoke(self, request: LLMRequest) -> Completion:
        """Issue the call and reduce the response."""
        config, sent = self._generation_config(request)

        response = self._client.models.generate_content(
            model=self.model_id, contents=request.prompt, config=config
        )

        usage = getattr(response, "usage_metadata", None)
        candidates = getattr(response, "candidates", None) or []
        finish_reason = (
            _name_of(getattr(candidates[0], "finish_reason", None)) if candidates else ""
        )

        raw: dict[str, Any] = {
            "wire": self.wire_record(sent, request),
            "finish_reason": finish_reason,
            "reasoning_tokens": _count(usage, "thoughts_token_count"),
        }

        block_reason = _name_of(
            getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
        )
        if block_reason:
            raw["block_reason"] = block_reason
            finish_reason = finish_reason or f"blocked:{block_reason}"

        return Completion(
            text=getattr(response, "text", None) or "",
            model_version=getattr(response, "model_version", "") or "",
            input_tokens=_count(usage, "prompt_token_count"),
            output_tokens=_count(usage, "candidates_token_count"),
            finish_reason=finish_reason or "stop",
            raw=raw,
        )

    def _translate(self, exc: Exception) -> ProviderError:
        """Sort an SDK exception by its HTTP status, falling back to transient for transport errors.

        A failure with no status never reached the service - a socket closed, a DNS lookup failed, a
        read timed out - and those are the failures most worth retrying during a job that runs for an
        hour.
        """
        status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        message = f"{type(exc).__name__}: {exc}"

        if isinstance(status, int):
            return self.classify_status(status, message)
        return TransientProviderError(message)


def _count(usage: Any, field: str) -> int:
    """A token count from the usage metadata, which omits fields it has nothing to report for."""
    return int(getattr(usage, field, None) or 0)


def _name_of(value: Any) -> str:
    """The name of an SDK enum member, as a plain string the ledger can serialize."""
    if value is None:
        return ""
    return str(getattr(value, "name", value))
