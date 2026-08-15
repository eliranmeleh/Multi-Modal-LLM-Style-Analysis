"""Enforce R1: no author name or corpus-specific identifier in ``src/``.

The book claims the method generalizes to any author's corpus by direct substitution. That claim is
either enforced by a test or it is decoration. This is the test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT, SRC_DIR

FORBIDDEN_TERMS_FILE = REPO_ROOT / "tests" / "forbidden_terms.txt"


def _load_forbidden_terms() -> list[str]:
    """Read the forbidden-term list, ignoring comments and blank lines."""
    lines = FORBIDDEN_TERMS_FILE.read_text(encoding="utf-8").splitlines()
    return [stripped for line in lines if (stripped := line.split("#", 1)[0].strip().lower())]


def _source_files() -> list[Path]:
    """Every Python source file in the package."""
    return sorted(SRC_DIR.rglob("*.py"))


def test_forbidden_terms_file_is_populated() -> None:
    """A silently empty list would make the whole check pass vacuously."""
    terms = _load_forbidden_terms()
    assert len(terms) >= 10, "the forbidden-term list looks truncated"
    assert all(term == term.lower() for term in terms)


def test_source_tree_is_not_empty() -> None:
    """Guards against the check passing because it found nothing to scan."""
    assert _source_files(), f"no Python sources found under {SRC_DIR}"


@pytest.mark.parametrize("term", _load_forbidden_terms())
def test_term_absent_from_sources(term: str) -> None:
    """No corpus-specific identifier appears anywhere in the package sources."""
    pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
    offenders: list[str] = []

    for path in _source_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert not offenders, (
        f"forbidden term '{term}' found in src/. It belongs in data/, configs/ or docs/:\n"
        + "\n".join(offenders)
    )
