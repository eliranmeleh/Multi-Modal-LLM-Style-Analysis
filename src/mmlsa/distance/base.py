"""The style-distance interface.

The distance is deliberately behind a protocol. The whole classification depends on the choice of
metric, so the specification treats FWED as *the metric the method is developed with*, one of a
family compared empirically in Phase B, rather than as a settled choice
(``docs/DECISIONS.md`` S6, I15).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class DistanceResult:
    """One chunk-to-rewrite distance, with the evidence behind it.

    ``detail`` is what makes the interpretability requirement real: for FWED it holds the aligned
    edit operations (``you -> thou``, ``does -> doth``), which is exactly the plain-language
    explanation a literary reader is shown. It is stored for a sampled subset of chunks only, since
    keeping it for all of them would dominate the run artifacts.
    """

    value: float
    n_units_original: int
    n_units_rewrite: int
    degenerate: bool = False
    detail: dict[str, Any] | None = field(default=None)

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"distance must lie in [0, 1], got {self.value}")


@runtime_checkable
class StyleDistance(Protocol):
    """Any style distance usable by the pipeline."""

    name: str

    def __call__(self, original: str, rewrite: str) -> DistanceResult:
        """Return the distance between an original chunk and its rewrite."""
        ...
