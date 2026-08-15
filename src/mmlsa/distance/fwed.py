"""Step 4 — Function-Word Edit Distance.

For an original chunk ``c`` and its rewrite ``r``::

    delta(c, r) = lev( FW(c), FW(r) ) / max( |FW(c)|, |FW(r)| )

where ``FW(x)`` is the ordered sequence of function words in ``x`` and ``lev`` is the Levenshtein
edit distance **between two sequences of tokens**, not between two strings of characters. The value
lies in ``[0, 1]`` and reads directly as the share of function-word usage the model had to change.

Normalizing by the larger of the two lengths makes the metric symmetric and insensitive to length
differences between a chunk and its rewrite.

See ``docs/SPEC.md`` section 3, Step 4, and the book's section 4.6.3.
"""

from __future__ import annotations

from functools import lru_cache

import Levenshtein

from mmlsa.distance.base import DistanceResult
from mmlsa.distance.tokenize import extract_function_words, load_function_words

PRIVATE_USE_AREA_START = 0xE000
"""First code point of the Basic Multilingual Plane private use area (U+E000 to U+F8FF)."""

PRIVATE_USE_AREA_SIZE = 0xF8FF - 0xE000 + 1


@lru_cache(maxsize=8)
def _code_point_map(function_words: tuple[str, ...]) -> dict[str, str]:
    """Map each function word to a unique private-use code point, assigned in sorted list order.

    ``python-Levenshtein`` operates on strings. Encoding each function word as a single character
    makes the string distance *exactly* the token-sequence distance, because the mapping is
    injective: no two words share a character and no word is a prefix of another. The alternative,
    running the string metric on the joined text, would silently measure character edits and would
    count ``thou`` against ``though`` as a two-character change rather than a substitution.
    """
    if len(function_words) > PRIVATE_USE_AREA_SIZE:
        raise ValueError(
            f"function-word list of {len(function_words)} exceeds the {PRIVATE_USE_AREA_SIZE} "
            "code points available in the private use area"
        )
    return {
        word: chr(PRIVATE_USE_AREA_START + index)
        for index, word in enumerate(sorted(function_words))
    }


def encode_sequence(sequence: list[str], function_words: tuple[str, ...]) -> str:
    """Encode a function-word sequence as a string of private-use code points."""
    mapping = _code_point_map(function_words)
    return "".join(mapping[word] for word in sequence)


def sequence_levenshtein(left: list[str], right: list[str], function_words: tuple[str, ...]) -> int:
    """Levenshtein distance between two token sequences, counted in tokens."""
    return Levenshtein.distance(
        encode_sequence(left, function_words), encode_sequence(right, function_words)
    )


def _edit_script(
    original: list[str], rewrite: list[str], function_words: tuple[str, ...]
) -> list[dict[str, object]]:
    """The aligned edit operations, in plain terms, for the interpretability requirement."""
    operations = Levenshtein.editops(
        encode_sequence(original, function_words), encode_sequence(rewrite, function_words)
    )
    script: list[dict[str, object]] = []
    for kind, source_index, target_index in operations:
        if kind == "replace":
            script.append(
                {
                    "op": "replace",
                    "at": source_index,
                    "from": original[source_index],
                    "to": rewrite[target_index],
                }
            )
        elif kind == "delete":
            script.append({"op": "delete", "at": source_index, "from": original[source_index]})
        else:
            script.append({"op": "insert", "at": source_index, "to": rewrite[target_index]})
    return script


class FunctionWordEditDistance:
    """The style distance the method is developed with.

    Instantiated once per run with the resolved path to the versioned function-word list, so that
    the list is read and validated a single time and every chunk is measured with the same
    instrument.
    """

    name = "fwed"

    def __init__(self, function_words_path: str, *, with_detail: bool = False) -> None:
        self._function_words = load_function_words(function_words_path)
        self._with_detail = with_detail

    @property
    def function_words(self) -> tuple[str, ...]:
        """The loaded function-word list, sorted."""
        return self._function_words

    def __call__(self, original: str, rewrite: str) -> DistanceResult:
        """Compute ``delta(original, rewrite)``.

        Edge cases, both specified:

        *Both sequences empty.* Defined as ``0.0`` and flagged ``degenerate``. A chunk with no
        function words at all carries no signal for this metric, and it is recorded so that it can
        be counted rather than quietly averaged in as a zero.

        *One sequence empty, the other not.* The distance is the length of the non-empty sequence
        over that same length, so ``1.0``. Every function word had to be introduced or removed.
        """
        fw_original = extract_function_words(original, self._function_words)
        fw_rewrite = extract_function_words(rewrite, self._function_words)

        denominator = max(len(fw_original), len(fw_rewrite))
        if denominator == 0:
            return DistanceResult(value=0.0, n_units_original=0, n_units_rewrite=0, degenerate=True)

        distance = sequence_levenshtein(fw_original, fw_rewrite, self._function_words)
        detail = (
            {"edits": _edit_script(fw_original, fw_rewrite, self._function_words)}
            if self._with_detail
            else None
        )

        return DistanceResult(
            value=distance / denominator,
            n_units_original=len(fw_original),
            n_units_rewrite=len(fw_rewrite),
            degenerate=False,
            detail=detail,
        )
