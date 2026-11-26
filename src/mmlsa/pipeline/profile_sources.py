"""Which creations a style profile's quoted examples come from.

Step 1 asks the model for the style of the corpus as a whole. In the M10 pilot one extraction call
over five creations returned a profile of the first one alone, and nothing in the scores or the
figures showed it; only reading the profile did (``docs/RESULTS.md`` F-15,
``docs/OPEN_QUESTIONS.md`` Q18). The examples a profile quotes give it away. An example that occurs
in only one creation of the run points at that creation, and when nearly all such examples point at
the same one, the profile describes that creation: Step 3 would rewrite every chunk toward it.
"Nearly all" rather than "all", because a common word can occur in only one play by chance: in the
pilot's run 3, four examples came from the first play and *fights* from another.

The check reads the profile and the run's texts and nothing else. It makes no call and changes
nothing in the method; the orchestrator decides what to do with its verdict
(``docs/DECISIONS.md`` I37).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from mmlsa.distance.tokenize import normalize_for_tokenizing

_SINGLE = re.compile(r"(?<![\w'])'([^'\n]+(?:'(?=\w)[^'\n]+)*)'(?!\w)")
"""A single-quoted example. The opening quote follows no letter, so a possessive or an elision in the
profile's own prose (``the play's``) opens nothing; an apostrophe between two letters stays inside
the example (``'ne'er'``)."""

_DOUBLE = re.compile(r'"([^"\n]+)"')
"""A double-quoted example."""

_LETTER = re.compile(r"[^\W\d_]")

_QUOTES = str.maketrans(
    {
        "\N{LEFT SINGLE QUOTATION MARK}": "'",
        "\N{LEFT DOUBLE QUOTATION MARK}": '"',
        "\N{RIGHT DOUBLE QUOTATION MARK}": '"',
    }
)
"""The opening single quote and both double quotes, folded to ASCII. The closing single quote is
already folded by :func:`normalize_for_tokenizing`, as an apostrophe."""


def _fold_quotes(text: str) -> str:
    """NFKC, with every typographic quote and apostrophe folded to ASCII."""
    return normalize_for_tokenizing(text).translate(_QUOTES)


def _normalize(text: str) -> str:
    """The form both sides are compared in: quotes folded, then casefolded."""
    return _fold_quotes(text).casefold()


def quoted_examples(profile: str) -> list[str]:
    """The examples a profile quotes, in order of first appearance, each once.

    A quotation with no letter in it (``'--'``) is punctuation being named, and one that starts or
    ends with a hyphen (``'-th'``, ``'un-'``) is an affix; neither is an example of the text.
    """
    folded = _fold_quotes(profile)
    found: list[tuple[int, str]] = []
    for pattern in (_SINGLE, _DOUBLE):
        found.extend((match.start(), match.group(1).strip()) for match in pattern.finditer(folded))

    examples: list[str] = []
    seen: set[str] = set()
    for _, example in sorted(found):
        key = example.casefold()
        is_affix = example.startswith("-") or example.endswith("-")
        if _LETTER.search(example) and not is_affix and key not in seen:
            seen.add(key)
            examples.append(example)
    return examples


def _pattern(example: str) -> re.Pattern[str]:
    """The example as whole words, with any run of whitespace between its words."""
    words = _normalize(example).split()
    return re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)")


@dataclass
class ProfileSources:
    """Where each quoted example occurs, and whether they all point at one creation."""

    examples: dict[str, list[str]]
    """Each example, with the creations it occurs in, in corpus order."""

    min_examples: int
    """How many attributable examples must point at one creation for a verdict."""

    min_share: float
    """The share of all attributable examples that must point at that creation, above one half."""

    @property
    def attributable(self) -> dict[str, str]:
        """The examples that occur in exactly one creation, with that creation."""
        return {example: where[0] for example, where in self.examples.items() if len(where) == 1}

    @property
    def by_creation(self) -> dict[str, int]:
        """How many attributable examples point at each creation."""
        return dict(Counter(self.attributable.values()))

    @property
    def one_source(self) -> str:
        """The creation the profile describes, or ``""`` when it describes no single one.

        That is the creation most attributable examples point at, when at least ``min_examples`` do
        and they are at least ``min_share`` of all of them. With ``min_share`` above one half, at
        most one creation can qualify.
        """
        counts = self.by_creation
        if not counts:
            return ""
        creation, n = max(counts.items(), key=lambda item: item[1])
        if n >= self.min_examples and n / sum(counts.values()) >= self.min_share:
            return creation
        return ""

    def to_dict(self) -> dict[str, Any]:
        """Plain data, for ``profiles/run_<i>_sources.json``."""
        return {
            "min_examples": self.min_examples,
            "min_share": self.min_share,
            "one_source": self.one_source,
            "by_creation": self.by_creation,
            "examples": self.examples,
        }


def profile_sources(
    profile: str, texts: dict[str, str], *, min_examples: int, min_share: float
) -> ProfileSources:
    """Find which of ``texts`` each example quoted in ``profile`` occurs in.

    ``texts`` is the run's corpus as Step 1 saw it, noise creation included. Matching is on whole
    words, case-insensitive, after the tokenizer's normalization, so ``'tis`` in a play is found by
    an example quoted as ``'tis'``.
    """
    normalized = {creation: _normalize(text) for creation, text in texts.items()}
    examples = {
        example: [creation for creation, text in normalized.items() if pattern.search(text)]
        for example, pattern in (
            (example, _pattern(example)) for example in quoted_examples(profile)
        )
    }
    return ProfileSources(examples=examples, min_examples=min_examples, min_share=min_share)
