"""The function-word list is part of the measurement instrument, so it is validated like data.

A silently duplicated or mis-cased entry would change every delta the project ever reports.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mmlsa.distance.tokenize import (
    MAX_LIST_ENTRIES,
    MIN_LIST_ENTRIES,
    FunctionWordListError,
    load_function_words,
)
from tests.conftest import REPO_ROOT

LIST_PATH = REPO_ROOT / "data" / "function_words" / "en_core_v1.txt"


def test_the_versioned_list_exists() -> None:
    """The path is referenced from configs/default.yaml and must actually resolve."""
    assert LIST_PATH.is_file()


def test_entries_are_lowercase_unique_sorted_and_within_the_expected_band() -> None:
    """Matches the book's "approximately 120 function words"."""
    words = load_function_words(str(LIST_PATH))

    assert MIN_LIST_ENTRIES <= len(words) <= MAX_LIST_ENTRIES
    assert list(words) == sorted(words)
    assert len(set(words)) == len(words)
    assert all(word == word.lower() for word in words)
    assert all(len(word.split()) == 1 for word in words)


def test_the_list_mixes_modern_and_early_modern_forms() -> None:
    """The point of the list: no prior about any one author's usage is baked into the metric.

    A list of only modern forms would measure archaism; a list of only Early Modern forms would
    measure modernity. Either would separate texts for reasons unrelated to authorship.
    """
    words = set(load_function_words(str(LIST_PATH)))

    modern = {"you", "your", "has", "does", "are", "it", "its"}
    early_modern = {"thou", "thee", "thy", "thine", "hath", "doth", "art", "dost"}

    assert modern <= words
    assert early_modern <= words


def test_comments_and_blank_lines_are_ignored(tmp_path: Path) -> None:
    """The shipped file documents its own composition in comments; those are not entries."""
    path = tmp_path / "list.txt"
    body = "\n".join(sorted({f"w{i}" for i in range(MIN_LIST_ENTRIES)}))
    path.write_text(f"# a comment\n\n{body}\n\n   \n# trailing comment\n", encoding="utf-8")

    assert len(load_function_words(str(path))) == MIN_LIST_ENTRIES


# ------------------------------------------------------------------------------ malformed lists


def test_a_duplicate_entry_is_rejected(tmp_path: Path) -> None:
    """A duplicate would not change results, but it means the file was hand-edited carelessly."""
    path = tmp_path / "dupes.txt"
    entries = sorted({f"w{i}" for i in range(MIN_LIST_ENTRIES)})
    path.write_text("\n".join([*entries, entries[0]]) + "\n", encoding="utf-8")

    with pytest.raises(FunctionWordListError, match="duplicate"):
        load_function_words(str(path))


def test_an_uppercase_entry_is_rejected(tmp_path: Path) -> None:
    """Extraction case-folds, so an uppercase entry would never match and would silently do nothing."""
    path = tmp_path / "case.txt"
    path.write_text(
        "\n".join(["The", *[f"w{i}" for i in range(MIN_LIST_ENTRIES)]]), encoding="utf-8"
    )

    with pytest.raises(FunctionWordListError, match="not lowercase"):
        load_function_words(str(path))


def test_a_multi_word_entry_is_rejected(tmp_path: Path) -> None:
    """Extraction works token by token, so a phrase entry could never match."""
    path = tmp_path / "phrase.txt"
    path.write_text(
        "\n".join(["as well as", *[f"w{i}" for i in range(MIN_LIST_ENTRIES)]]), encoding="utf-8"
    )

    with pytest.raises(FunctionWordListError, match="whitespace"):
        load_function_words(str(path))


@pytest.mark.parametrize("count", [MIN_LIST_ENTRIES - 1, MAX_LIST_ENTRIES + 1])
def test_a_list_outside_the_sanity_band_is_rejected(tmp_path: Path, count: int) -> None:
    """A truncated or bloated list is caught here rather than showing up as odd deltas."""
    path = tmp_path / f"band_{count}.txt"
    path.write_text("\n".join(sorted({f"w{i}" for i in range(count)})), encoding="utf-8")

    with pytest.raises(FunctionWordListError, match="expected between"):
        load_function_words(str(path))


def test_a_missing_list_is_reported_by_path(tmp_path: Path) -> None:
    """Misconfiguring the path must fail immediately, not produce empty sequences."""
    with pytest.raises(FunctionWordListError, match="not found"):
        load_function_words(str(tmp_path / "absent.txt"))
