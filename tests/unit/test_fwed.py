"""Step 4 — the Function-Word Edit Distance.

These tests protect the number the whole project reports. A wrong distance does not crash: it
produces a plausible score, a plausible threshold and a plausible list of suspicious creations.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mmlsa.distance.fwed import FunctionWordEditDistance, sequence_levenshtein
from mmlsa.distance.registry import available, build_distance
from mmlsa.distance.tokenize import load_function_words
from tests.conftest import REPO_ROOT

LIST_PATH = str(REPO_ROOT / "data" / "function_words" / "en_core_v1.txt")


@pytest.fixture(scope="module")
def delta() -> FunctionWordEditDistance:
    """The distance under test, built once for the module."""
    return FunctionWordEditDistance(LIST_PATH)


@pytest.fixture(scope="module")
def function_words() -> tuple[str, ...]:
    """The shipped v1 list."""
    return load_function_words(LIST_PATH)


def reference_levenshtein(left: list[str], right: list[str]) -> int:
    """A plain dynamic-programming Levenshtein over token sequences.

    Deliberately naive and independent of the production path, which encodes each token as a
    private-use code point and defers to a C library. Two implementations that agree on a thousand
    random inputs are unlikely to share a bug.
    """
    previous = list(range(len(right) + 1))
    for i, left_token in enumerate(left, start=1):
        current = [i]
        for j, right_token in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_token != right_token),
                )
            )
        previous = current
    return previous[-1]


# ------------------------------------------------------------------------------- the golden case


def test_golden_case_hand_computed(delta: FunctionWordEditDistance) -> None:
    """A worked example whose arithmetic is written out, re-derived rather than copied.

    original: "Do you know what he does when the night comes?"
    rewrite : "Dost thou know what he doth when the night comes?"

    Tokenizing and keeping only members of the v1 list:

        FW(original) = [do,   you,  what, he, does, the]     |FW(c)| = 6
        FW(rewrite)  = [dost, thou, what, he, doth, the]     |FW(r)| = 6

    ``know``, ``night`` and ``comes`` are content words and are dropped. ``when`` is dropped as
    well: the v1 list has no wh-adverbs (see docs/OPEN_QUESTIONS.md Q10). Both sequences are
    therefore six tokens long, aligning position for position:

        position 0:  do   -> dost   substitution
        position 1:  you  -> thou   substitution
        position 2:  what == what
        position 3:  he   == he
        position 4:  does -> doth   substitution
        position 5:  the  == the

    Three substitutions, no insertions, no deletions, so lev = 3.

        delta = 3 / max(6, 6) = 3 / 6 = 0.5
    """
    result = delta(
        "Do you know what he does when the night comes?",
        "Dost thou know what he doth when the night comes?",
    )

    assert result.n_units_original == 6
    assert result.n_units_rewrite == 6
    assert result.value == pytest.approx(0.5)
    assert result.degenerate is False


def test_golden_case_edit_script_reads_in_plain_terms() -> None:
    """The interpretability requirement: the edit script is the explanation shown to a reader."""
    with_detail = FunctionWordEditDistance(LIST_PATH, with_detail=True)
    result = with_detail(
        "Do you know what he does when the night comes?",
        "Dost thou know what he doth when the night comes?",
    )

    assert result.detail is not None
    edits = result.detail["edits"]
    assert [(e["from"], e["to"]) for e in edits] == [
        ("do", "dost"),
        ("you", "thou"),
        ("does", "doth"),
    ]
    assert all(edit["op"] == "replace" for edit in edits)


def test_edit_script_records_insertions() -> None:
    """A rewrite that adds function words reports them as insertions, with the word inserted."""
    with_detail = FunctionWordEditDistance(LIST_PATH, with_detail=True)
    result = with_detail("the cat sat", "the cat sat on the mat")

    assert result.detail is not None
    inserts = [e for e in result.detail["edits"] if e["op"] == "insert"]
    assert [e["to"] for e in inserts] == ["on", "the"]


def test_edit_script_records_deletions() -> None:
    """A rewrite that drops function words reports them as deletions, with the word removed."""
    with_detail = FunctionWordEditDistance(LIST_PATH, with_detail=True)
    result = with_detail("the cat sat on the mat", "the cat sat")

    assert result.detail is not None
    deletes = [e for e in result.detail["edits"] if e["op"] == "delete"]
    assert [e["from"] for e in deletes] == ["on", "the"]


def test_no_detail_is_stored_unless_it_is_asked_for() -> None:
    """Storing the edit script for every chunk would dominate the run artifacts."""
    without_detail = FunctionWordEditDistance(LIST_PATH)

    assert without_detail("the cat", "thou cat").detail is None


# ------------------------------------------------------------------------------------- properties


@pytest.mark.parametrize(
    "text",
    [
        "To be, or not to be, that is the question.",
        "The quick brown fox jumps over the lazy dog.",
        "Thou art the man that hath done this unto me.",
        "and and and of of the",
        "Cats sleep peacefully.",
    ],
)
def test_identity_is_zero(delta: FunctionWordEditDistance, text: str) -> None:
    """``delta(x, x) == 0``. A rewrite identical to the original is valid, not an error."""
    assert delta(text, text).value == 0.0


@given(
    left=st.lists(st.sampled_from(["the", "and", "thou", "you", "of", "hath", "cat"]), max_size=40),
    right=st.lists(
        st.sampled_from(["the", "and", "thou", "you", "of", "hath", "cat"]), max_size=40
    ),
)
@settings(max_examples=200, deadline=None)
def test_symmetry(left: list[str], right: list[str]) -> None:
    """Symmetric, because the normalizer ``max(|a|, |b|)`` is symmetric."""
    delta = FunctionWordEditDistance(LIST_PATH)
    forward = delta(" ".join(left), " ".join(right))
    backward = delta(" ".join(right), " ".join(left))

    assert forward.value == pytest.approx(backward.value)


@given(
    left=st.text(alphabet="abcdefg ", max_size=200),
    right=st.text(alphabet="abcdefg ", max_size=200),
)
@settings(max_examples=200, deadline=None)
def test_value_always_lies_in_the_unit_interval(left: str, right: str) -> None:
    """The metric is reported as a share, so a value outside [0, 1] is meaningless."""
    delta = FunctionWordEditDistance(LIST_PATH)

    assert 0.0 <= delta(left, right).value <= 1.0


# ------------------------------------------------------------------------------------ edge cases


def test_both_sequences_empty_is_zero_and_flagged_degenerate(
    delta: FunctionWordEditDistance,
) -> None:
    """A chunk with no function words carries no signal, and is counted rather than averaged in blind."""
    result = delta("cats sleep peacefully", "dogs bark loudly")

    assert result.value == 0.0
    assert result.degenerate is True
    assert result.n_units_original == 0
    assert result.n_units_rewrite == 0


@pytest.mark.parametrize(
    ("original", "rewrite"),
    [
        ("cats sleep", "the cat doth sleep"),
        ("the cat doth sleep", "cats sleep"),
    ],
)
def test_one_sequence_empty_gives_one(
    delta: FunctionWordEditDistance, original: str, rewrite: str
) -> None:
    """Every function word had to be introduced or removed, so the share changed is 1."""
    result = delta(original, rewrite)

    assert result.value == 1.0
    assert result.degenerate is False


def test_completely_disjoint_sequences_of_equal_length_give_one(
    delta: FunctionWordEditDistance,
) -> None:
    """Upper bound reached when the two sequences share nothing at any position."""
    result = delta("the of and", "thou hath art")

    assert result.value == 1.0


def test_insertions_are_normalized_by_the_longer_sequence(
    delta: FunctionWordEditDistance,
) -> None:
    """Normalization uses the longer sequence, so appending material cannot exceed 1.

    original: "the cat of the house"                     FW = [the, of, the]                 3
    rewrite : "the cat of the house and of the garden"   FW = [the, of, the, and, of, the]   6

    ``cat``, ``house`` and ``garden`` are content words and drop out. The rewrite's sequence extends
    the original's by three tokens, so lev = 3 insertions and delta = 3 / max(3, 6) = 0.5.
    """
    result = delta("the cat of the house", "the cat of the house and of the garden")

    assert result.n_units_original == 3
    assert result.n_units_rewrite == 6
    assert result.value == pytest.approx(3 / 6)


# ------------------------------------------------------ fast path against an independent reference


@given(
    left=st.lists(
        st.sampled_from(["the", "and", "of", "thou", "you", "hath", "is", "not"]), max_size=30
    ),
    right=st.lists(
        st.sampled_from(["the", "and", "of", "thou", "you", "hath", "is", "not"]), max_size=30
    ),
)
@settings(max_examples=1000, deadline=None)
def test_code_point_fast_path_agrees_with_the_reference_implementation(
    left: list[str], right: list[str]
) -> None:
    """The private-use-area encoding must give exactly the token-sequence distance."""
    words = load_function_words(LIST_PATH)

    assert sequence_levenshtein(left, right, words) == reference_levenshtein(left, right)


def test_encoding_does_not_confuse_a_word_with_its_prefix(
    function_words: tuple[str, ...],
) -> None:
    """``thou`` against ``though`` is one substitution, not a partial character-level match.

    Running a string metric on the joined text would score these as similar. Encoding each token as
    a single code point is what makes the distance count tokens.
    """
    assert "thou" in function_words
    assert "though" in function_words
    assert sequence_levenshtein(["thou"], ["though"], function_words) == 1


# -------------------------------------------------------------------------------------- registry


def test_the_registry_exposes_the_default_metric() -> None:
    """The metric is selected by config, so it must be reachable by name."""
    assert "fwed" in available()

    metric = build_distance("fwed", LIST_PATH)
    assert metric.name == "fwed"
    assert metric("the cat", "the cat").value == 0.0


def test_an_unknown_metric_fails_with_the_available_names() -> None:
    """A specified-but-unimplemented metric must fail here, not deep inside the scoring loop."""
    with pytest.raises(ValueError, match="Available"):
        build_distance("not_a_metric", LIST_PATH)
