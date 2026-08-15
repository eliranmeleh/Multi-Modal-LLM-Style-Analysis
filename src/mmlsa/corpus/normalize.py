"""Normalization, applied once at ingest.

What is stored in ``data/corpus/`` is the normalized text, and chunking, rewriting and distance all
operate on it, so the pipeline is deterministic from this point onward.

The governing principle is **do as little as possible**. Original orthography is the signal: the
distance metric counts `thou` against `you` and `hath` against `has`, so lowercasing, modernizing or
stripping punctuation here would destroy exactly what the method measures. Only two classes of
material are removed, and both are editorial rather than authorial.

Front-matter removal is the one heuristic step in the whole pipeline. Every removal is therefore
**recorded per text** in the manifest, so that a rule which fires on forty texts and misses nine is
visible as a number rather than discovered later as an unexplained score.

See ``docs/DATA.md`` section 4 and ``docs/OPEN_QUESTIONS.md`` Q4.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

NORMALIZATION_VERSION = 1
"""Bumped when any rule below changes. Recorded in the manifest; changing it invalidates checksums."""

_QUOTES = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "“": '"',
    "”": '"',
    "„": '"',
}
_DASHES = ("—", "–")

_TRANSCRIBER_NOTE = re.compile(
    r"^[ \t]*\[?\s*(transcriber'?s?|editor'?s?|producer'?s?)\s+note.*?(?:\]|\n\s*\n)",
    re.IGNORECASE | re.DOTALL | re.MULTILINE,
)
_CONTENTS_HEADING = re.compile(r"^[ \t]*contents[ \t]*$", re.IGNORECASE | re.MULTILINE)
_PERSONS_HEADING = re.compile(
    r"^[ \t]*[(\[]?\s*("
    r"dramatis\s+person(?:ae|æ|as)"
    r"|(?:the\s+)?persons\s+represented"
    r"|the\s+persons\s+of\s+the\s+play"
    r"|characters\s+in\s+the\s+play"
    r"|(?:the\s+)?actors?['’]?s?\s+names?"
    r"|the\s+names\s+of\s+the\s+actors"
    r")",
    re.IGNORECASE | re.MULTILINE,
)
"""The cast list heading, in the several forms the corpus actually uses.

Three things this has to tolerate, each found in a real file rather than imagined:

* the ``æ`` ligature, which NFKC leaves intact and the 1500-series files use;
* trailing text on the same line, as in "The Actors Names in the History of Sir John Oldcastle";
* the heading broken across lines, as in "THE / ACTORS / NAME", which ``\\s+`` spans because it
  matches a newline.

It is deliberately not anchored to the end of the line. Matching is confined to the opening
``_FRONT_MATTER_LIMIT`` of a text and only ever moves the start of the body forward to the next act
or scene heading, so a loose match cannot silently delete dialogue.
"""

_BODY_START = re.compile(
    r"^[ \t]*(act[ \t]+(?:i|1|the\s+first)\b|prologue\b|scene[ \t]+(?:i|1)\b|induction\b)",
    re.IGNORECASE | re.MULTILINE,
)
"""Where the author's text begins. Front matter is only ever removed *before* this point."""

_FRONT_MATTER_LIMIT = 0.30
_FRONT_MATTER_FLOOR_CHARS = 4_000
"""Front matter is only ever looked for near the opening of a text.

Without a bound, a cast list reprinted in an appendix, or the word "Prologue" spoken in Act V, could
anchor the cut and delete most of a creation. The rules may only ever remove an opening.

The bound is a fraction **or** a fixed floor, whichever is larger. A pure fraction fails on short
inputs: thirty percent of a two-paragraph text is a few dozen characters, so a cast list that plainly
is front matter falls outside the window and survives. The floor is far below the length of any real
creation, where the fraction always dominates.
"""


def _front_matter_horizon(text: str) -> int:
    """How far into a text the front-matter rules are allowed to look."""
    return max(int(len(text) * _FRONT_MATTER_LIMIT), _FRONT_MATTER_FLOOR_CHARS)


@dataclass
class NormalizationReport:
    """What normalization actually did to one text, for the manifest."""

    removed_transcriber_notes: int = 0
    removed_contents: bool = False
    removed_persons: bool = False
    removed_front_matter_words: int = 0
    front_matter_rule: str = "none"
    notes: list[str] = field(default_factory=list)


def _strip_front_matter(text: str, report: NormalizationReport) -> str:
    """Remove the opening editorial apparatus: a scene list and a cast list.

    The Gutenberg play files are laid out as::

        TITLE / by <author>
        ACT I  Scene I. ...  Scene II. ...      <- a table of contents, listing every scene
        Dramatis Personae  <names>              <- a cast list
        ACT I  SCENE I. ...  <dialogue>         <- the author's text, repeating the headings

    Anchoring on the *first* act heading therefore lands inside the table of contents, not at the
    play. Two rules handle it, tried in order, and which one fired is recorded:

    ``after_cast_list``  the reliable case. Find the cast list, then take the first act or scene
    heading after it. The cast list sits between the contents and the body in every file that has
    one, so this cuts both in one step.

    ``repeated_heading``  the fallback when there is no cast list. If the first act heading appears
    again verbatim later on, the first occurrence was a contents entry and the second is the body.

    If neither applies the text is left alone. A creation that keeps a few lines of apparatus is a
    far smaller problem than one that loses its first act, so every rule here only ever removes an
    opening, and only within the first ``_FRONT_MATTER_LIMIT`` of the text.
    """
    horizon = _front_matter_horizon(text)

    persons = _PERSONS_HEADING.search(text, 0, horizon)
    if persons is not None:
        body = _BODY_START.search(text, persons.end())
        if body is not None and body.start() <= horizon:
            report.removed_persons = True
            report.removed_contents = _CONTENTS_HEADING.search(text, 0, persons.start()) is not None
            report.front_matter_rule = "after_cast_list"
            report.removed_front_matter_words = len(text[: body.start()].split())
            return text[body.start() :]

    first = _BODY_START.search(text)
    if first is None:
        report.notes.append("no act or scene heading found; front matter left untouched")
        return text

    heading = text[first.start() : text.find("\n", first.start())].strip()
    if heading:
        repeat = text.find(f"\n{heading}", first.end())
        if 0 < repeat <= horizon:
            report.front_matter_rule = "repeated_heading"
            report.removed_contents = True
            report.removed_front_matter_words = len(text[: repeat + 1].split())
            return text[repeat + 1 :]

    report.notes.append("no cast list and no repeated heading; front matter left untouched")
    return text


def normalize(text: str) -> tuple[str, NormalizationReport]:
    """Apply the ingest normalization and report what was removed.

    Rules, in order:

    1. Unicode NFKC.
    2. Typographic quotes to ASCII; en and em dashes to a spaced hyphen.
    3. Transcriber and editor notes removed.
    4. A leading table of contents and cast list removed, if a body start follows them.
    5. Trailing whitespace stripped per line; runs of three or more blank lines collapsed to two.

    Note what is **not** done: no lowercasing, no punctuation stripping, no spelling modernization,
    no line re-wrapping, and no removal of speaker prefixes or stage directions. Speaker prefixes
    are stylistically inert for function-word analysis, and a selective-removal heuristic would
    behave differently across fifty differently-typeset files.
    """
    report = NormalizationReport()

    text = unicodedata.normalize("NFKC", text)
    for source, target in _QUOTES.items():
        text = text.replace(source, target)
    for dash in _DASHES:
        text = text.replace(dash, " - ")

    text, count = _TRANSCRIBER_NOTE.subn("", text)
    report.removed_transcriber_notes = count

    text = _strip_front_matter(text, report)

    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip() + "\n", report


def count_words(text: str) -> int:
    """A word is a maximal run of non-whitespace characters, consistently with chunking."""
    return len(text.split())
