"""Which creations a style profile's quoted examples come from (#28, Q18, I37)."""

from __future__ import annotations

import pytest

from mmlsa.pipeline.profile_sources import profile_sources, quoted_examples

TEXTS = {
    "first": "Sirrah, fetch the scrivener. Money, money, money!\nThe mortgage is due, i'faith.",
    "second": "Good morrow, sirrah. The king's men ride at dawn; 'tis cold.",
    "third": "What, ho! The ninny spurns his fortune; 'tis ever so.",
}


# --------------------------------------------------------------------------- finding the examples


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("archaic terms like 'sirrah', 'yfaith' and 'codpiece'.", ["sirrah", "yfaith", "codpiece"]),
        ('repetition ("money, money, money") for emphasis', ["money, money, money"]),
        (
            "curly quotes, \N{LEFT SINGLE QUOTATION MARK}scrivener\N{RIGHT SINGLE QUOTATION MARK} and \N{LEFT DOUBLE QUOTATION MARK}mortgage\N{RIGHT DOUBLE QUOTATION MARK}",
            ["scrivener", "mortgage"],
        ),
        ("contractions such as 'tis', 'twas'", ["tis", "twas"]),
        ("elided forms like 'ne'er' and 'i'faith'", ["ne'er", "i'faith"]),
    ],
)
def test_the_quoted_examples_are_found(profile: str, expected: list[str]) -> None:
    assert quoted_examples(profile) == expected


def test_an_apostrophe_in_prose_opens_no_quotation() -> None:
    """A possessive or an elision in the profile's own sentences is not an example."""
    assert quoted_examples("The play's register shifts; the servants' speech is low.") == []


def test_a_quotation_without_a_letter_is_not_an_example() -> None:
    assert quoted_examples("Dashes ('--') and ellipses ('...') mark pauses.") == []


def test_a_word_ending_is_not_an_example() -> None:
    """'-th' names an ending, not a word, and as a search string it finds noise (pilot run 2)."""
    assert quoted_examples("the '-th' ending, 'un-' prefixes and 'doth'") == ["doth"]


def test_an_example_quoted_twice_is_counted_once() -> None:
    assert quoted_examples("'Sirrah' here, and 'sirrah' again.") == ["Sirrah"]


# ---------------------------------------------------------------------------- where they occur


def test_an_example_is_attributed_to_the_only_creation_that_contains_it() -> None:
    sources = profile_sources(
        "terms like 'scrivener' and 'ninny'", TEXTS, min_examples=2, min_share=0.75
    )

    assert sources.examples == {"scrivener": ["first"], "ninny": ["third"]}
    assert sources.attributable == {"scrivener": "first", "ninny": "third"}


def test_an_example_in_several_creations_points_at_none() -> None:
    sources = profile_sources("address by 'sirrah'", TEXTS, min_examples=1, min_share=0.75)

    assert sources.examples == {"sirrah": ["first", "second"]}
    assert sources.attributable == {}


def test_an_example_matches_whole_words_only() -> None:
    """'mort' is not in 'mortgage', and 'king' is in "king's"."""
    sources = profile_sources("'mort' and 'king'", TEXTS, min_examples=1, min_share=0.75)

    assert sources.examples == {"mort": [], "king": ["second"]}


def test_a_phrase_matches_across_case_punctuation_and_a_line_break() -> None:
    profile = "repetition such as 'money, money, money' and 'money! the mortgage'"
    sources = profile_sources(profile, TEXTS, min_examples=1, min_share=0.75)

    assert sources.examples["money, money, money"] == ["first"]
    assert sources.examples["money! the mortgage"] == ["first"]


def test_an_elided_example_matches_the_elided_word() -> None:
    sources = profile_sources(
        "forms like 'tis' and 'i'faith'", TEXTS, min_examples=1, min_share=0.75
    )

    assert sources.examples == {"tis": ["second", "third"], "i'faith": ["first"]}


# ------------------------------------------------------------------------------------ the verdict


def test_a_profile_whose_examples_all_come_from_one_creation_describes_that_creation() -> None:
    """The M10 pilot's case (F-15): every example found in one play comes from the first."""
    profile = "terms like 'scrivener', 'mortgage' and 'sirrah'; 'money, money, money'"
    sources = profile_sources(profile, TEXTS, min_examples=2, min_share=0.75)

    assert sources.one_source == "first"
    assert sources.by_creation == {"first": 3}


def test_one_stray_example_does_not_hide_a_one_creation_profile() -> None:
    """Pilot run 3: four examples from the first play and one common word found in another."""
    profile = "'scrivener', 'mortgage', 'money, money, money', 'i'faith' and 'ninny'"
    sources = profile_sources(profile, TEXTS, min_examples=3, min_share=0.75)

    assert sources.by_creation == {"first": 4, "third": 1}
    assert sources.one_source == "first"


def test_examples_from_two_creations_describe_no_single_one() -> None:
    sources = profile_sources(
        "'scrivener', 'mortgage', 'ninny'", TEXTS, min_examples=2, min_share=0.75
    )

    assert sources.one_source == ""
    assert sources.by_creation == {"first": 2, "third": 1}


def test_too_few_examples_give_no_verdict() -> None:
    """One example from one play says little; the threshold is a configuration value."""
    sources = profile_sources("a term like 'scrivener'", TEXTS, min_examples=2, min_share=0.75)

    assert sources.attributable == {"scrivener": "first"}
    assert sources.one_source == ""


def test_a_profile_that_quotes_nothing_passes() -> None:
    sources = profile_sources(
        "Long coordinated clauses, frequent inversion.", TEXTS, min_examples=1, min_share=0.75
    )

    assert sources.examples == {}
    assert sources.one_source == ""


def test_the_record_lists_every_example_and_the_verdict() -> None:
    sources = profile_sources(
        "'scrivener', 'mortgage', 'sirrah'", TEXTS, min_examples=2, min_share=0.75
    )

    assert sources.to_dict() == {
        "min_examples": 2,
        "min_share": 0.75,
        "one_source": "first",
        "by_creation": {"first": 2},
        "examples": {"scrivener": ["first"], "mortgage": ["first"], "sirrah": ["first", "second"]},
    }
