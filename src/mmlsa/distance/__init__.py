"""Style distances: the tokenizer, the metrics, and the registry that selects between them."""

from mmlsa.distance.base import DistanceResult, StyleDistance
from mmlsa.distance.fwed import FunctionWordEditDistance
from mmlsa.distance.registry import available, build_distance, register

__all__ = [
    "DistanceResult",
    "FunctionWordEditDistance",
    "StyleDistance",
    "available",
    "build_distance",
    "register",
]
