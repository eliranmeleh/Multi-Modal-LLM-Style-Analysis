"""The provider registry.

The provider is one configuration key (R4). Adding a backend means adding a module here and one
registry entry; nothing under ``src/mmlsa/pipeline/`` may import a concrete provider.

Only the offline providers are registered. The three live backends named in the approved book are
wired at milestone M9, where they are compared on measured rewrite fidelity before one is chosen.
Registering them earlier would mean shipping code that has never issued a request.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mmlsa.llm.base import LLMProvider
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.providers.fake import FakeProvider
from mmlsa.llm.providers.replay import ReplayProvider

_REGISTRY: dict[str, Callable[..., LLMProvider]] = {
    FakeProvider.name: FakeProvider,
    ReplayProvider.name: ReplayProvider,
}

PLANNED = ("gemini", "openai", "anthropic")
"""Named in the approved book, implemented at M9. Listed so the error message can say so."""


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
        if name in PLANNED:
            raise UnknownProviderError(
                f"provider '{name}' is named in the specification but is not implemented until "
                f"milestone M9. Available now: {', '.join(available())}."
            )
        raise UnknownProviderError(
            f"unknown provider '{name}'. Available: {', '.join(available())}."
        )

    if factory is ReplayProvider:
        if cache is None:
            raise UnknownProviderError("the replay provider requires a cache to read from")
        return ReplayProvider(cache, model_id=model_id, **options)

    return factory(model_id=model_id, **options)


__all__ = [
    "PLANNED",
    "FakeProvider",
    "ReplayProvider",
    "UnknownProviderError",
    "available",
    "build_provider",
    "register",
]
