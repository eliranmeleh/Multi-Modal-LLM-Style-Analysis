"""Cleaning model responses.

Models wrap answers in things nobody asked for: Markdown fences, a line of introduction, an offer to
help further. None of it is part of the answer, and all of it would be measured as though it were.

Used by both Step 1 and Step 3, which is why it lives here rather than in either.
"""

from __future__ import annotations

import re

_CODE_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n?|\n?\s*```\s*$")


def strip_code_fences(text: str) -> str:
    """Remove Markdown fencing wrapped around a whole response.

    Only fences at the very start and end are removed. A fence in the middle of a response is
    content as far as this project is concerned, and guessing otherwise risks deleting text.
    """
    cleaned = text.strip()
    previous = None
    while cleaned != previous:
        previous = cleaned
        cleaned = _CODE_FENCE.sub("", cleaned).strip()
    return cleaned
