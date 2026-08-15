"""What the three live backends share.

Each provider module below this one is thin on purpose: build a client, translate one request, read
one response. Everything that is the same for all three lives here, because three copies of the same
credential handling is three chances to leak a key.

Four concerns, in the order they bite:

*Credentials (R6).* The key is read from the environment at **construction**, never from a config
file, and is handed straight to the SDK client without being stored on the instance. A provider built
in an environment with no key raises immediately, which is what stops a test suite from issuing a
real, billable request: ``tests/conftest.py`` removes the three key variables before every test, so
constructing a live provider there fails at once rather than calling out.

*Optional dependencies.* The three SDKs are extras (``pip install 'mmlsa[gemini]'``). They are
imported inside the constructor rather than at module scope, so the registry can name all three
backends on a machine that has none of them installed.

*Retries belong to the runner.* Every SDK ships its own retry loop. They are all switched off here.
``Runner`` already owns rate limiting, exponential backoff with jitter, and the transient/permanent
distinction, and two retry layers multiply rather than add: five runner attempts over two SDK
attempts is ten calls and ten times the sleep.

*An empty completion is an error, not an empty rewrite.* A refusal, a safety block or an output
budget spent entirely on reasoning tokens all return successfully with no text. Passing that through
would score the chunk against an empty string, which is the maximum possible distance, and the
creation would look maximally suspicious for a reason that has nothing to do with its author. So it
raises, the chunk is marked failed, and ``rewrite.max_failed_fraction`` decides whether the run
survives.

See ``docs/ARCHITECTURE.md`` section 3.1 and ``docs/DECISIONS.md`` I24.
"""

from __future__ import annotations

import importlib
import os
import time
from dataclasses import dataclass
from types import ModuleType
from typing import Any, ClassVar

from mmlsa.llm.base import (
    LLMRequest,
    LLMResponse,
    PermanentProviderError,
    ProviderError,
    TransientProviderError,
)
from mmlsa.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ModelSpec:
    """What this project needs to know about one model before it calls it.

    ``accepts_temperature`` is not a detail. ``docs/SPEC.md`` Step 3 fixes ``temperature = 0``, and
    several current models **reject the parameter outright** rather than ignoring it, so a faithful
    request is a failed request. The flag is what lets the provider send the specified value where it
    is accepted and record its absence where it is not (``docs/OPEN_QUESTIONS.md`` Q14).
    """

    context_window: int
    accepts_temperature: bool = True
    reasoning: str = "none"
    """How the model's own reasoning is switched off: ``none`` (nothing to switch), ``disable``
    (an explicit off), ``minimum`` (cannot be switched off, hold it as low as permitted), or
    ``always_on`` (cannot be influenced; the request must not mention it)."""

    min_reasoning_tokens: int = 0
    """The floor for ``minimum``, where a provider refuses a budget of zero."""


@dataclass(frozen=True)
class Completion:
    """One provider response, already reduced to the fields the ledger records."""

    text: str
    model_version: str
    input_tokens: int
    output_tokens: int
    finish_reason: str
    raw: dict[str, Any]


def load_sdk(module_name: str, extra: str, provider: str) -> ModuleType:
    """Import an optional SDK, or say exactly how to install it."""
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
        raise PermanentProviderError(
            f"the '{provider}' provider needs the '{module_name}' package, which is an optional "
            f"extra. Install it with: pip install 'mmlsa[{extra}]'"
        ) from exc


def read_key(env_var: str, provider: str) -> str:
    """Read an API key from the environment, and never from anywhere else (R6)."""
    key = os.environ.get(env_var, "").strip()
    if not key:
        raise PermanentProviderError(
            f"the '{provider}' provider needs {env_var} in the environment. Copy .env.example to "
            ".env and set it there, or export it in your shell. A key must never be written into a "
            "config file or a run artifact."
        )
    return key


class LiveProvider:
    """Base for the backends that issue real requests.

    Subclasses supply the four class attributes, a ``_connect`` that builds an SDK client, an
    ``_invoke`` that performs one call, and a ``_translate`` that sorts the SDK's exceptions into
    transient and permanent.
    """

    name = ""
    """Deliberately not a ``ClassVar``: the ``LLMProvider`` protocol declares ``name`` as an
    instance attribute, and a class variable does not satisfy an instance-variable protocol member."""

    env_var: ClassVar[str] = ""
    extra: ClassVar[str] = ""
    sdk_module: ClassVar[str] = ""
    default_model_id: ClassVar[str] = ""
    models: ClassVar[dict[str, ModelSpec]] = {}
    unknown_model: ClassVar[ModelSpec] = ModelSpec(context_window=128_000)

    def __init__(
        self,
        model_id: str | None = None,
        *,
        timeout_seconds: int = 120,
        context_window: int | None = None,
        **_: Any,
    ) -> None:
        self.model_id = model_id or self.default_model_id
        self.spec = self.spec_for(self.model_id)
        self.timeout_seconds = timeout_seconds
        self._context_window = context_window or self.spec.context_window
        self.calls = 0
        self._sdk = load_sdk(self.sdk_module, self.extra, self.name)
        self._client = self._connect(read_key(self.env_var, self.name))

    # -- configuration ---------------------------------------------------------------------------

    @classmethod
    def spec_for(cls, model_id: str) -> ModelSpec:
        """The capabilities of one model.

        Providers publish new models faster than a student project can track them, so an unlisted
        identifier is not an error: it takes conservative defaults and says so. Matching falls back
        to the longest listed prefix, which is what makes a dated snapshot behave like the alias it
        was cut from.
        """
        if model_id in cls.models:
            return cls.models[model_id]

        prefixes = [known for known in cls.models if model_id.startswith(known)]
        if prefixes:
            return cls.models[max(prefixes, key=len)]

        logger.warning(
            "provider.unlisted_model",
            provider=cls.name,
            model_id=model_id,
            note="using conservative defaults; add it to the model table to pin its capabilities",
        )
        return cls.unknown_model

    def context_window(self) -> int:
        """Total token capacity, used by Step 1 to pack whole creations into each profile call."""
        return self._context_window

    def send_temperature(self) -> bool:
        """Whether the specified temperature can actually be transmitted to this model."""
        return self.spec.accepts_temperature

    # -- the call --------------------------------------------------------------------------------

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Issue one request, timing it and refusing to return an empty completion."""
        started = time.perf_counter()
        self.calls += 1

        try:
            outcome = self._invoke(request)
        except ProviderError:
            raise
        except Exception as exc:
            # Every SDK exception, without exception, is re-raised as a classified ProviderError:
            # the runner decides what to retry from the type, and an unclassified escape would
            # abort a run that is fifty minutes in.
            raise self._translate(exc) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        text = outcome.text.strip()

        if not text:
            raise PermanentProviderError(
                f"{self.name} returned no text (finish reason '{outcome.finish_reason}', "
                f"{outcome.output_tokens} output tokens). An empty rewrite would be scored against "
                "an empty string, which is the maximum possible distance, so it is refused here "
                "rather than recorded as a result."
            )

        raw = dict(outcome.raw)
        raw.setdefault("provider", self.name)

        return LLMResponse(
            text=text,
            model_id=self.model_id,
            model_version=outcome.model_version or self.model_id,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            latency_ms=latency_ms,
            finish_reason=outcome.finish_reason,
            raw=raw,
        )

    # -- subclass responsibilities ---------------------------------------------------------------

    def _connect(self, api_key: str) -> Any:
        """Build the SDK client. The key is passed through and never stored on ``self``."""
        raise NotImplementedError

    def _invoke(self, request: LLMRequest) -> Completion:
        """Perform one call and reduce the provider's response to a :class:`Completion`."""
        raise NotImplementedError

    def _translate(self, exc: Exception) -> ProviderError:
        """Sort an SDK exception into transient or permanent."""
        raise NotImplementedError

    # -- shared helpers --------------------------------------------------------------------------

    @staticmethod
    def classify_status(status: int | None, message: str) -> ProviderError:
        """The HTTP-status rule the three SDKs agree on.

        408, 409, 429 and anything at or above 500 are worth another attempt. Everything else is a
        request that will fail again in exactly the same way.
        """
        if status is not None and (status in {408, 409, 429} or status >= 500):
            return TransientProviderError(message)
        return PermanentProviderError(message)

    def wire_record(self, sent: dict[str, Any], request: LLMRequest) -> dict[str, Any]:
        """The parameters actually put on the wire, for the ledger (R2).

        The specification pins ``temperature = 0``. When a model rejects the parameter the request is
        still made, with the omission recorded here, so that a reader of ``calls.jsonl`` can tell the
        difference between "sampling was pinned" and "sampling was left to the provider's default".
        """
        record: dict[str, Any] = {"model_id": self.model_id, **sent}
        if not self.send_temperature():
            record["temperature_requested"] = request.temperature
            record["temperature_sent"] = False
        return record


__all__ = [
    "Completion",
    "LiveProvider",
    "ModelSpec",
    "load_sdk",
    "read_key",
]
