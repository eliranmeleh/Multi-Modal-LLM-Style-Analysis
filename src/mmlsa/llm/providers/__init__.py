"""The provider registry.

The provider is one configuration key (R4). Adding a backend means adding a module here and one
registry entry; nothing under ``src/mmlsa/pipeline/`` may import a concrete provider.

Five backends: two offline, three live. Importing this module never imports a provider SDK - the
three live modules load theirs inside their constructors - so the registry can name every backend on
a machine that has none of the optional extras installed, and a configuration error is reported
before a dependency error.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mmlsa.llm.base import LLMProvider
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.providers.anthropic import AnthropicProvider
from mmlsa.llm.providers.fake import FakeProvider
from mmlsa.llm.providers.gemini import GeminiProvider
from mmlsa.llm.providers.openai import OpenAIProvider
from mmlsa.llm.providers.replay import ReplayProvider

_REGISTRY: dict[str, Callable[..., LLMProvider]] = {
    AnthropicProvider.name: AnthropicProvider,
    FakeProvider.name: FakeProvider,
    GeminiProvider.name: GeminiProvider,
    OpenAIProvider.name: OpenAIProvider,
    ReplayProvider.name: ReplayProvider,
}

LIVE = (AnthropicProvider.name, GeminiProvider.name, OpenAIProvider.name)
"""The backends that issue real requests. Each needs its own extra and its own key."""

OFFLINE = (FakeProvider.name, ReplayProvider.name)
"""The backends that never touch the network, and the only ones any test may use (R5)."""


class UnknownProviderError(Exception):
    """Raised when the configured provider does not exist yet."""


def register(name: str, factory: Callable[..., LLMProvider]) -> None:
    """Register a provider implementation."""
    if name in _REGISTRY:
        raise ValueError(f"provider '{name}' is already registered")
    _REGISTRY[name] = factory


def available() -> list[str]:
    """The names of every registered provider."""
    return sorted(_REGISTRY)


def default_model(name: str) -> str:
    """The model a provider falls back to when ``llm.model_id`` is unset, or an empty string.

    Worth reporting before a wide job: the default is a real choice with a real price, and a dry run
    that names the provider but not the model leaves the most expensive decision implicit.
    """
    return str(getattr(_REGISTRY.get(name), "default_model_id", "") or "")


def declared_context_window(name: str, model_id: str | None = None) -> int | None:
    """The context window of a configured model, without building a client or holding a key.

    A dry run has to report the right number of profile-extraction calls before anything is spent,
    and that count depends on the window. Asking a provider would mean credentials; consulting the
    model table does not. ``None`` means the provider declares no fixed window - the offline two do
    not - and the caller should keep its own assumption.
    """
    factory = _REGISTRY.get(name)
    spec_for = getattr(factory, "spec_for", None)
    if spec_for is None:
        return None

    resolved = model_id or getattr(factory, "default_model_id", "")
    window: int = spec_for(resolved).context_window
    return window


def build_provider(
    name: str,
    *,
    model_id: str | None = None,
    cache: ResponseCache | None = None,
    **options: Any,
) -> LLMProvider:
    """Construct the configured provider.

    ``cache`` is passed to providers that need it; ``ReplayProvider`` is the only one that does, and
    it cannot be built without one.
    """
    factory = _REGISTRY.get(name)
    if factory is None:
        raise UnknownProviderError(
            f"unknown provider '{name}'. Available: {', '.join(available())}."
        )

    if factory is ReplayProvider:
        if cache is None:
            raise UnknownProviderError("the replay provider requires a cache to read from")
        return ReplayProvider(cache, model_id=model_id, **options)

    return factory(model_id=model_id, **options)


__all__ = [
    "LIVE",
    "OFFLINE",
    "AnthropicProvider",
    "FakeProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "ReplayProvider",
    "UnknownProviderError",
    "available",
    "build_provider",
    "declared_context_window",
    "default_model",
    "register",
]
