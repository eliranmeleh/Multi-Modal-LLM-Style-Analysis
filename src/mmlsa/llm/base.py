"""The provider interface, and the error taxonomy the runner reasons about.

Everything the pipeline knows about a language model is in this file: roughly forty lines of
protocol, deliberately. The project does not need an LLM abstraction framework
(``docs/ARCHITECTURE.md`` section 10), it needs one seam narrow enough that swapping the provider is
a single configuration key (R4).

The error taxonomy matters as much as the protocol. A run of several thousand calls will hit rate
limits and transient failures, and the difference between "wait and try again" and "this will never
work" has to be a type rather than a guess at a message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ProviderError(Exception):
    """Base class for anything that goes wrong talking to a model."""


class TransientProviderError(ProviderError):
    """A failure that may succeed on a retry: rate limiting, a 5xx, a timeout.

    Retried with exponential backoff and full jitter, up to ``llm.max_transient_retries``.
    """


class PermanentProviderError(ProviderError):
    """A failure that retrying cannot fix: bad credentials, a malformed request, a refused model.

    Recorded in the ledger and does not abort the run; the affected unit of work is marked failed.
    """


class CacheMissError(ProviderError):
    """Raised when a response is not in the cache and the run is not permitted to call out.

    This is the whole point of ``replay`` mode: a published run must reproduce from its recorded
    artifacts exactly, so a miss is a hard error rather than a quiet new call.
    """


@dataclass(frozen=True)
class LLMRequest:
    """One request to a model. Every field participates in the cache key.

    ``prompt_schema_version`` is carried on the request rather than held globally because each
    template is versioned separately (``docs/PROMPTS.md`` section 0). Bumping one template's version
    invalidates exactly the entries that used it, and nothing else.
    """

    prompt: str
    system: str | None = None
    temperature: float = 0.0
    max_output_tokens: int = 4096
    response_format: str = "text"
    tag: str = ""
    prompt_schema_version: int = 1

    def cache_fields(self, provider_name: str, model_id: str) -> dict[str, Any]:
        """The fields that define response identity, for hashing.

        ``tag`` is deliberately excluded: it labels what the call is *for*, not what was asked, and
        including it would mean the same prompt issued from two places missed the cache twice.
        """
        return {
            "provider": provider_name,
            "model_id": model_id,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "response_format": self.response_format,
            "system": self.system,
            "prompt": self.prompt,
            "prompt_schema_version": self.prompt_schema_version,
        }


@dataclass(frozen=True)
class LLMResponse:
    """One response from a model, with everything the ledger has to record (R2)."""

    text: str
    model_id: str
    model_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str = "stop"
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Plain data, for the cache and the ledger."""
        return {
            "text": self.text,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LLMResponse:
        """Rebuild a response from cached data."""
        return cls(
            text=payload["text"],
            model_id=payload["model_id"],
            model_version=payload["model_version"],
            input_tokens=payload.get("input_tokens", 0),
            output_tokens=payload.get("output_tokens", 0),
            latency_ms=payload.get("latency_ms", 0),
            finish_reason=payload.get("finish_reason", "stop"),
            raw=payload.get("raw", {}),
        )


@runtime_checkable
class LLMProvider(Protocol):
    """What the pipeline requires of a model backend.

    Implementations must pass ``tests/contract/test_provider_contract.py``. Nothing under
    ``src/mmlsa/pipeline/`` may import a concrete provider.
    """

    name: str
    model_id: str

    def context_window(self) -> int:
        """Total token capacity of the configured model, used to pack the profile calls."""
        ...

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Issue one request and return the response."""
        ...
