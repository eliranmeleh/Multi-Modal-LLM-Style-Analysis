"""Normalization and function-word extraction.

Every rule here is one that, if broken, silently changes the sequence being measured.
"""

from __future__ import annotations

import pytest

from mmlsa.distance.tokenize import (
    extract_function_words,
    load_function_words,
    normalize_for_tokenizing,
    tokenize,
)
from tests.conftest import REPO_ROOT

LIST_PATH = str(REPO_ROOT / "data" / "function_words" / "en_core_v1.txt")


@pytest.fixture(scope="module")
def function_words() -> tuple[str, ...]:
    """The shipped v1 list."""
    return load_function_words(LIST_PATH)


# ------------------------------------------------------------------------------------ tokenizing


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Hello, world!", ["hello", "world"]),
        ('He said "stop".', ["he", "said", "stop"]),
        ("(parenthetical)", ["parenthetical"]),
        ("dash - separated", ["dash", "separated"]),
        ("[stage direction]", ["stage", "direction"]),
        ("ellipsis...", ["ellipsis"]),
        ("*emphasis*", ["emphasis"]),
        ("master-cord", ["master-cord"]),
    ],
)
def test_edge_punctuation_is_stripped(raw: str, expected: list[str]) -> None:
    """Punctuation is removed from token edges only; a hyphen inside a compound word is kept."""
    assert tokenize(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("em—dash", ["em", "dash"]),
        ("en–dash", ["en", "dash"]),
        ("do--well", ["do", "well"]),
        ("there---on", ["there", "on"]),
        ("love-letters—and", ["love-letters", "and"]),
    ],
)
def test_a_dash_between_two_words_separates_them(raw: str, expected: list[str]) -> None:
    """An em dash, an en dash or a run of hyphens splits words even with no space around it (I34)."""
    assert tokenize(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("'tis,", ["'tis"]),
        ("th' morning", ["th'", "morning"]),
        ("ne'er", ["ne'er"]),
        ("don't", ["don't"]),
        ("it's", ["it's"]),
    ],
)
def test_apostrophes_survive_tokenizing(raw: str, expected: list[str]) -> None:
    """Early Modern elisions are meaningful tokens and must not be mangled."""
    assert tokenize(raw) == expected


def test_case_is_folded() -> None:
    """``The`` and ``the`` must reach the same list entry."""
    assert tokenize("The THE tHe") == ["the", "the", "the"]


def test_typographic_apostrophes_fold_to_ascii() -> None:
    """Gutenberg texts mix both forms; they must tokenize identically."""
    assert tokenize("’tis") == tokenize("'tis")
    assert normalize_for_tokenizing("’") == "'"


def test_empty_and_whitespace_input_produce_no_tokens() -> None:
    """Nothing in, nothing out; no empty-string token slips through."""
    assert tokenize("") == []
    assert tokenize("   \n\t ") == []
    assert tokenize("... --- ***") == []


# --------------------------------------------------------------------------- function-word extraction


def test_content_words_are_dropped(function_words: tuple[str, ...]) -> None:
    """Only list members survive; this is what makes the metric content-independent."""
    assert extract_function_words("the quick brown fox", function_words) == ["the"]


def test_order_is_preserved_and_repeats_are_kept(function_words: tuple[str, ...]) -> None:
    """``FW(x)`` is a sequence, not a set and not a bag. Order is the signal."""
    extracted = extract_function_words("the cat and the dog and the bird", function_words)

    assert extracted == ["the", "and", "the", "and", "the"]


def test_reordering_the_source_changes_the_sequence(function_words: tuple[str, ...]) -> None:
    """If order did not matter this metric would be a frequency vector, which it deliberately is not."""
    forward = extract_function_words("of the people by the state", function_words)
    backward = extract_function_words("by the people of the state", function_words)

    assert sorted(forward) == sorted(backward)
    assert forward != backward


def test_contraction_is_not_confused_with_a_possessive(function_words: tuple[str, ...]) -> None:
    """Stripping apostrophes would turn ``it's`` into ``its``, which *is* a list entry.

    This is the concrete reason the tokenizer excludes the apostrophe from its strip set.
    """
    assert "its" in function_words
    assert extract_function_words("it's late", function_words) == []
    assert extract_function_words("its hour", function_words) == ["its"]


def test_punctuation_attached_to_a_function_word_does_not_hide_it(
    function_words: tuple[str, ...],
) -> None:
    """``the,`` and ``the`` must both be found, or line-final words would be lost."""
    assert extract_function_words("the, the; the! (the)", function_words) == ["the"] * 4


def test_a_dash_the_model_writes_does_not_hide_a_function_word(
    function_words: tuple[str, ...],
) -> None:
    """Issue #15, passage ``king_henry_viii_0036``: the corpus writes the dash as a spaced hyphen,
    the rewrite as an em dash with no spaces. Both must give the same sequence, or FWED counts the
    lost ``on`` as an edit that is no change of style.
    """
    original = extract_function_words(
        "and wot you what I found There - on my conscience", function_words
    )
    rewrite = extract_function_words(
        "and wot you what I found There—on my conscience", function_words
    )

    assert original == ["and", "you", "what", "i", "on", "my"]
    assert rewrite == original


def test_a_text_with_no_function_words_yields_an_empty_sequence(
    function_words: tuple[str, ...],
) -> None:
    """The degenerate case the distance has to handle explicitly."""
    assert extract_function_words("cats sleep peacefully", function_words) == []


def test_early_modern_and_modern_forms_are_both_extracted(
    function_words: tuple[str, ...],
) -> None:
    """Both registers reach the sequence, which is what lets the distance compare them."""
    modern = extract_function_words("do you know what he does", function_words)
    early = extract_function_words("dost thou know what he doth", function_words)

    assert modern == ["do", "you", "what", "he", "does"]
    assert early == ["dost", "thou", "what", "he", "doth"]
