"""Gutenberg boilerplate stripping and ingest normalization.

Normalization is where a corpus silently goes wrong: nothing crashes, the text just is not quite
what anyone thinks it is. Each rule is pinned, and so is each rule's refusal to guess.
"""

from __future__ import annotations

import pytest

from mmlsa.corpus.gutenberg import GutenbergError, has_residual_marker, strip_boilerplate
from mmlsa.corpus.normalize import count_words, normalize

HEADER = """The Project Gutenberg eBook of Something

This eBook is for the use of anyone anywhere at no cost.

*** START OF THE PROJECT GUTENBERG EBOOK SOMETHING ***
"""
FOOTER = """
*** END OF THE PROJECT GUTENBERG EBOOK SOMETHING ***

Updated editions will replace the previous one.
"""


def wrap(body: str) -> str:
    """Wrap a body in realistic Gutenberg boilerplate."""
    return HEADER + body + FOOTER


# ------------------------------------------------------------------------- boilerplate stripping


def test_material_outside_the_markers_is_removed() -> None:
    """The licence header and footer must not reach the corpus."""
    stripped = strip_boilerplate(wrap("\nACT I\nScene I.\nTo be or not to be.\n"))

    assert "To be or not to be." in stripped
    assert not has_residual_marker(stripped)


@pytest.mark.parametrize(
    "start_line",
    [
        "*** START OF THE PROJECT GUTENBERG EBOOK HAMLET ***",
        "***START OF THE PROJECT GUTENBERG EBOOK HAMLET***",
        "*** START OF THIS PROJECT GUTENBERG EBOOK HAMLET ***",
        "*** start of the project gutenberg ebook hamlet ***",
    ],
)
def test_marker_spelling_variants_are_recognized(start_line: str) -> None:
    """Gutenberg's delimiters differ by the era a text was posted."""
    text = f"preamble\n{start_line}\nACT I\nbody text here\n*** END OF THE PROJECT GUTENBERG EBOOK HAMLET ***\ntail"

    assert "body text here" in strip_boilerplate(text)


@pytest.mark.parametrize(
    "text",
    [
        "no markers at all, just text",
        "*** START OF THE PROJECT GUTENBERG EBOOK X ***\nbody with no end marker",
        "*** END OF THE PROJECT GUTENBERG EBOOK X ***\nend marker only",
    ],
)
def test_a_missing_marker_raises_rather_than_guessing(text: str) -> None:
    """A guessed cut point prepends legal English to a creation and inflates its function words."""
    with pytest.raises(GutenbergError):
        strip_boilerplate(text, source="probe")


def test_an_empty_body_between_markers_raises() -> None:
    """A file that downloaded as headers only must not pass as a zero-length creation."""
    with pytest.raises(GutenbergError, match="empty"):
        strip_boilerplate(HEADER + "\n   \n" + FOOTER)


def test_the_error_names_the_text_it_came_from() -> None:
    """With fifty texts to check, an unattributed failure costs an hour."""
    with pytest.raises(GutenbergError, match="my_creation"):
        strip_boilerplate("nothing here", source="my_creation")


# ---------------------------------------------------------------------------------- what is kept


def test_original_orthography_survives_normalization() -> None:
    """Early Modern forms are the signal. Modernizing them here would destroy the measurement."""
    text, _ = normalize("ACT I\nThou hast thy wish; doth he not know 'tis so?")

    for form in ("Thou", "hast", "thy", "doth", "'tis"):
        assert form in text


def test_case_and_punctuation_are_preserved() -> None:
    """Lowercasing and punctuation stripping happen in the distance tokenizer, never at ingest."""
    text, _ = normalize("ACT I\nEnter HAMLET. To be, or not to be: that is the question!")

    assert "HAMLET" in text
    assert "To be, or not to be:" in text
    assert "question!" in text


def test_speaker_prefixes_and_stage_directions_are_kept() -> None:
    """docs/OPEN_QUESTIONS.md Q4: kept as printed, applied identically to every text."""
    text, _ = normalize("ACT I\nHAMLET.\nA little more than kin.\n[Aside.]\nExeunt.")

    assert "HAMLET." in text
    assert "[Aside.]" in text
    assert "Exeunt." in text


# ------------------------------------------------------------------------------ character folding


def test_typographic_quotes_fold_to_ascii() -> None:
    """Gutenberg texts mix both forms; leaving both would split identical tokens in two."""
    text, _ = normalize("ACT I\n‘single’ and “double” and ’tis")

    assert "'single'" in text
    assert '"double"' in text
    assert "'tis" in text
    for character in ("‘", "’", "“", "”"):
        assert character not in text


def test_dashes_become_a_spaced_hyphen() -> None:
    """An em dash glued to a word would otherwise hide the word from the tokenizer."""
    text, _ = normalize("ACT I\nthe king—my father–is dead")

    assert "—" not in text
    assert "–" not in text
    assert "king - my" in text


# ------------------------------------------------------------------------------- front matter


def test_a_table_of_contents_before_the_first_act_is_removed() -> None:
    """Editorial apparatus, not the author's text."""
    raw = "Contents\nACT I\nScene I. Elsinore.\nScene II. A room.\n\nACT I\nSCENE I.\nWho's there?"
    text, report = normalize(raw)

    assert report.removed_contents is True
    assert text.startswith("ACT I")
    assert "Who's there?" in text


def test_a_cast_list_before_the_first_act_is_removed() -> None:
    """The dramatis personae is a list of names, not prose, and would skew nothing but noise."""
    raw = "PERSONS REPRESENTED.\nHamlet, son to the King.\nHoratio, friend to Hamlet.\n\nACT I\nWho's there?"
    text, report = normalize(raw)

    assert report.removed_persons is True
    assert "friend to Hamlet" not in text
    assert "Who's there?" in text


def test_nothing_is_removed_when_no_act_heading_follows() -> None:
    """A poem has no acts. Removing its opening because it looked like front matter would be a bug."""
    raw = "Contents\nA poem with no act headings at all, only verse lines running on."
    text, report = normalize(raw)

    assert report.removed_contents is False
    assert "Contents" in text
    assert report.notes


def test_front_matter_after_the_body_starts_is_left_alone() -> None:
    """The rules only ever look before the first act heading."""
    raw = "ACT I\nWho's there?\n\nContents\nthis is dialogue, oddly\n"
    text, report = normalize(raw)

    assert report.removed_contents is False
    assert "this is dialogue, oddly" in text


def test_transcriber_notes_are_removed_and_counted() -> None:
    """Counted rather than silently dropped, so the manifest shows how often the rule fired."""
    raw = "[Transcriber's Note: spelling has been retained.]\n\nACT I\nWho's there?"
    text, report = normalize(raw)

    assert report.removed_transcriber_notes == 1
    assert "spelling has been retained" not in text


# ------------------------------------------------------------------------------------ whitespace


def test_blank_line_runs_collapse_and_trailing_spaces_go() -> None:
    """Cosmetic, but it keeps checksums stable across editions that differ only in whitespace."""
    text, _ = normalize("ACT I\nfirst line   \n\n\n\n\nsecond line\t\n")

    assert "   \n" not in text
    assert "\n\n\n" not in text
    assert "first line\n\nsecond line" in text


def test_lines_are_not_rewrapped() -> None:
    """Re-wrapping would change nothing measurable but would make every diff unreadable."""
    text, _ = normalize("ACT I\nshort\nlines\nstay\nshort")

    assert text.count("\n") >= 4


def test_normalization_is_idempotent() -> None:
    """Running it twice must not change the result, or checksums drift on re-ingest."""
    once, _ = normalize("ACT I\n‘quoted’ text—here\n\n\n\nmore")
    twice, _ = normalize(once)

    assert once == twice


def test_word_count_matches_whitespace_splitting() -> None:
    """The same definition of a word that chunking uses."""
    assert count_words("one two  three\nfour\tfive") == 5
    assert count_words("   ") == 0
