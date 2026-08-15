"""The style-distance registry.

Phase B compares several distances on the *same recorded rewrites*, so the metric has to be
selectable by configuration without touching pipeline code. The registry exists from day one; only
``fwed`` is implemented until that comparison is actually scheduled (``docs/DECISIONS.md`` I15).
"""

from __future__ import annotations

from collections.abc import Callable

from mmlsa.distance.base import StyleDistance
from mmlsa.distance.fwed import FunctionWordEditDistance

DistanceFactory = Callable[..., StyleDistance]

_REGISTRY: dict[str, DistanceFactory] = {
    FunctionWordEditDistance.name: FunctionWordEditDistance,
}


def register(name: str, factory: DistanceFactory) -> None:
    """Register a distance implementation under ``name``."""
    if name in _REGISTRY:
        raise ValueError(f"distance '{name}' is already registered")
    _REGISTRY[name] = factory


def available() -> list[str]:
    """The names of every registered distance."""
    return sorted(_REGISTRY)


def build_distance(
    name: str, function_words_path: str, *, with_detail: bool = False
) -> StyleDistance:
    """Construct the configured distance.

    An unimplemented but specified metric fails here with a message naming what is available, rather
    than failing later with an attribute error deep inside the scoring loop.
    """
    factory = _REGISTRY.get(name)
    if factory is None:
        raise ValueError(f"unknown distance '{name}'. Available: {', '.join(available())}")
    return factory(function_words_path, with_detail=with_detail)
