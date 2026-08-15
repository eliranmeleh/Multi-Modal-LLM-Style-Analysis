"""Normalization and function-word extraction, ``FW(x)``.

This module is the measurement instrument. The distance is computed over the sequence it produces
and over nothing else, so the exact order of these steps is part of the specification rather than an
implementation detail. See ``docs/DATA.md`` section 5.

The one rule that is easy to get wrong: **apostrophes are never stripped**. Elided forms
(``'tis``, ``th'``, ``ne'er``) are meaningful tokens, and stripping the apostrophe would silently
turn ``'tis`` into ``tis`` and drop it from every sequence. It would also turn ``it's`` into ``its``,
which *is* a list entry, and quietly count a contraction as a possessive pronoun.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

EDGE_PUNCTUATION = '.,;:!?"()[]{}<>*_—–-'
"""Characters stripped from the edges of a token. Deliberately excludes the apostrophe."""

MIN_LIST_ENTRIES = 110
MAX_LIST_ENTRIES = 130
"""Sanity band for the function-word list, matching the book's "approximately 120"."""


class FunctionWordListError(Exception):
    """Raised when the function-word list is missing or malformed."""


def normalize_for_tokenizing(text: str) -> str:
    """NFKC normalize and fold typographic apostrophes to ASCII.

    Applied only inside the distance tokenizer. The stored corpus keeps its original orthography,
    because the LLM is asked to rewrite real text (``docs/DATA.md`` section 4, rule 6).
    """
    return unicodedata.normalize("NFKC", text).replace("’", "'")


def tokenize(text: str) -> list[str]:
    """Split text into lowercase, edge-punctuation-stripped tokens.

    Steps, in this order: NFKC normalize, fold apostrophes, casefold, split on whitespace, strip
    edge punctuation, discard empties.
    """
    normalized = normalize_for_tokenizing(text).casefold()
    tokens = []
    for raw in normalized.split():
        token = raw.strip(EDGE_PUNCTUATION)
        if token:
            tokens.append(token)
    return tokens


@lru_cache(maxsize=8)
def load_function_words(path: str) -> tuple[str, ...]:
    """Load the versioned function-word list, sorted and validated.

    Cached by path: the list is read once per process and shared by every chunk.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FunctionWordListError(f"function-word list not found: {file_path}")

    entries: list[str] = []
    for lineno, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        if entry != entry.lower():
            raise FunctionWordListError(f"{file_path}:{lineno}: entry '{entry}' is not lowercase")
        if len(entry.split()) != 1:
            raise FunctionWordListError(
                f"{file_path}:{lineno}: entry '{entry}' contains whitespace"
            )
        entries.append(entry)

    unique = sorted(set(entries))
    if len(unique) != len(entries):
        duplicates = sorted({e for e in entries if entries.count(e) > 1})
        raise FunctionWordListError(f"{file_path}: duplicate entries {duplicates}")
    if not MIN_LIST_ENTRIES <= len(unique) <= MAX_LIST_ENTRIES:
        raise FunctionWordListError(
            f"{file_path}: {len(unique)} entries, expected between "
            f"{MIN_LIST_ENTRIES} and {MAX_LIST_ENTRIES}"
        )

    return tuple(unique)


def extract_function_words(text: str, function_words: tuple[str, ...]) -> list[str]:
    """Return ``FW(x)``: the ordered sequence of function words in ``text``.

    The result is a **sequence**, not a set and not a bag. Order is preserved and repeats are kept:
    that is what makes the edit distance sensitive to syntactic style rather than to vocabulary
    frequency alone, and it is the property that distinguishes this metric from a Burrows's Delta
    style frequency vector.
    """
    vocabulary = frozenset(function_words)
    return [token for token in tokenize(text) if token in vocabulary]
