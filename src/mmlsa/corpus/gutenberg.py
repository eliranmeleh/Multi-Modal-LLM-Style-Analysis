"""Fetching from Project Gutenberg and stripping its boilerplate.

Two jobs, kept separate from normalization because they are the two places a text can be silently
wrong: the wrong file, or the right file with a licence header left in the middle of the corpus.

The boilerplate markers are matched strictly. When a marker is missing the text is **rejected**
rather than guessed at, because a guessed cut point silently prepends a few hundred words of legal
English to a creation and inflates every one of its function-word counts.

See ``docs/DATA.md`` section 4.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request

START_MARKER = re.compile(
    r"^\s*\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*\s*$",
    re.IGNORECASE | re.MULTILINE,
)
END_MARKER = re.compile(
    r"^\s*\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*\s*$",
    re.IGNORECASE | re.MULTILINE,
)
"""Both the modern and the older spacing variants of the Gutenberg delimiters."""

RESIDUAL_MARKER = re.compile(r"PROJECT GUTENBERG", re.IGNORECASE)
"""Any surviving mention in a normalized file means the strip did not do its job."""

MIRRORS = (
    "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt",
    "https://www.gutenberg.org/files/{id}/{id}-0.txt",
    "https://www.gutenberg.org/files/{id}/{id}.txt",
)
"""Tried in order. Gutenberg's file layout differs by the era a text was posted."""

USER_AGENT = (
    "mmlsa/0.1 (academic research; https://github.com/eliranmeleh/Multi-Modal-LLM-Style-Analysis)"
)


class GutenbergError(Exception):
    """Raised when a text cannot be fetched or its boilerplate cannot be located."""


def download(
    gutenberg_id: int,
    *,
    timeout: int = 60,
    retries: int = 3,
    pause_seconds: float = 1.0,
) -> str:
    """Fetch one text, trying each known URL layout in turn.

    A pause is taken between requests. Project Gutenberg is a donated public service and blocks
    clients that hammer it; a corpus of fifty texts does not need to be fetched quickly.
    """
    errors: list[str] = []

    for attempt in range(retries):
        for template in MIRRORS:
            url = template.format(id=gutenberg_id)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read()
            except (urllib.error.URLError, TimeoutError) as exc:
                errors.append(f"{url}: {exc}")
                continue

            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    return raw.decode("utf-8-sig")
                except UnicodeDecodeError as exc:
                    raise GutenbergError(
                        f"text {gutenberg_id} at {url} is not valid UTF-8: {exc}"
                    ) from exc

        if attempt < retries - 1:
            time.sleep(pause_seconds * (2**attempt))

    raise GutenbergError(
        f"could not download Gutenberg text {gutenberg_id}. Tried:\n  " + "\n  ".join(errors)
    )


def strip_boilerplate(text: str, *, source: str = "") -> str:
    """Return only the material between the Gutenberg start and end markers.

    Raises rather than guessing when either marker is absent or they appear in the wrong order.
    """
    label = f" in {source}" if source else ""

    start = START_MARKER.search(text)
    if start is None:
        raise GutenbergError(
            f"no Project Gutenberg START marker found{label}. Refusing to guess where the text "
            "begins; inspect the file by hand."
        )

    end = END_MARKER.search(text, start.end())
    if end is None:
        raise GutenbergError(
            f"no Project Gutenberg END marker found after the START marker{label}. "
            "Refusing to guess where the text ends; inspect the file by hand."
        )

    body = text[start.end() : end.start()]
    if not body.strip():
        raise GutenbergError(f"the region between the Gutenberg markers is empty{label}")
    return body


def has_residual_marker(text: str) -> bool:
    """Whether any Project Gutenberg boilerplate survives. Used by ``corpus verify``."""
    return RESIDUAL_MARKER.search(text) is not None
