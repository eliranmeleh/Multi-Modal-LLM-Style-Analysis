"""Step 5 — aggregation.

The arithmetic here is simple enough that it looks not worth testing, which is exactly why it is
worth testing: an off-by-one in the divisor, or a NaN reaching the threshold, changes the published
result without changing anything visible.
"""

from __future__ import annotations

import math
import statistics

import pytest

from mmlsa.pipeline.score import (
    ChunkDelta,
    ChunkStatus,
    aggregate_creation,
    aggregate_run,
    scorable_scores,
)


def make_deltas(
    values: list[float],
    *,
    creation_id: str = "text_a",
    n_words: int = 400,
    status: ChunkStatus = ChunkStatus.OK,
) -> list[ChunkDelta]:
    """Build a list of chunk deltas with uniform metadata."""
    return [
        ChunkDelta(
            creation_id=creation_id,
            chunk_index=index,
            delta=value,
            n_words=n_words,
            status=status,
        )
        for index, value in enumerate(values)
    ]


# ------------------------------------------------------------------------- mean over chunks


def test_run_mean_matches_a_hand_computed_case() -> None:
    """(0.10 + 0.20 + 0.30 + 0.40) / 4 = 1.00 / 4 = 0.25."""
    result = aggregate_run("text_a", 1, make_deltas([0.10, 0.20, 0.30, 0.40]))

    assert result.mean_delta == pytest.approx(0.25)
    assert result.n_chunks_used == 4
    assert result.n_chunks_total == 4


def test_failed_chunks_are_excluded_and_the_divisor_is_the_successful_count() -> None:
    """Deltas 0.1 and 0.3 succeed, two fail: the mean is 0.4 / 2 = 0.2, not 0.4 / 4 = 0.1."""
    deltas = [
        ChunkDelta("text_a", 0, 0.1, 400, ChunkStatus.OK),
        ChunkDelta("text_a", 1, 0.0, 400, ChunkStatus.FAILED),
        ChunkDelta("text_a", 2, 0.3, 400, ChunkStatus.OK),
        ChunkDelta("text_a", 3, 0.0, 400, ChunkStatus.FAILED),
    ]
    result = aggregate_run("text_a", 1, deltas)

    assert result.mean_delta == pytest.approx(0.2)
    assert result.n_chunks_used == 2
    assert result.n_chunks_failed == 2
    assert result.n_chunks_total == 4
    assert result.failed_fraction == pytest.approx(0.5)


def test_a_run_with_every_chunk_failed_has_no_mean() -> None:
    """``None``, not ``NaN``: a NaN would propagate silently into the threshold."""
    result = aggregate_run("text_a", 1, make_deltas([0.0, 0.0], status=ChunkStatus.FAILED))

    assert result.mean_delta is None
    assert result.n_chunks_used == 0


def test_degenerate_chunks_are_counted_but_still_scored() -> None:
    """A chunk with no function words has delta 0 by definition; it is counted, not dropped."""
    deltas = [
        ChunkDelta("text_a", 0, 0.4, 400, ChunkStatus.OK),
        ChunkDelta("text_a", 1, 0.0, 400, ChunkStatus.OK, degenerate=True),
    ]
    result = aggregate_run("text_a", 1, deltas)

    assert result.mean_delta == pytest.approx(0.2)
    assert result.n_chunks_degenerate == 1


def test_length_weighted_mean_differs_when_chunks_differ_in_length() -> None:
    """The sensitivity check from OPEN_QUESTIONS Q3, computed alongside the specified mean.

    A full 400-word chunk at 0.10 and a 40-word tail at 0.60:
      unweighted     = (0.10 + 0.60) / 2 = 0.35
      length-weighted = (0.10*400 + 0.60*40) / 440 = (40 + 24) / 440 = 64 / 440 = 0.14545...
    """
    deltas = [
        ChunkDelta("text_a", 0, 0.10, 400, ChunkStatus.OK),
        ChunkDelta("text_a", 1, 0.60, 40, ChunkStatus.OK),
    ]
    result = aggregate_run("text_a", 1, deltas)

    assert result.mean_delta == pytest.approx(0.35)
    assert result.length_weighted_mean == pytest.approx(64 / 440)


# --------------------------------------------------------------------------- mean over runs


def test_creation_score_matches_a_hand_computed_case() -> None:
    """Per-run scores [0.042, 0.044, 0.041] average to 0.127 / 3 = 0.042333..."""
    runs = [
        aggregate_run("text_a", 1, make_deltas([0.042])),
        aggregate_run("text_a", 2, make_deltas([0.044])),
        aggregate_run("text_a", 3, make_deltas([0.041])),
    ]
    result = aggregate_creation("text_a", runs)

    assert result.score == pytest.approx(0.127 / 3)
    assert result.per_run == pytest.approx([0.042, 0.044, 0.041])
    assert result.n_runs_scored == 3


def test_standard_deviation_uses_ddof_one() -> None:
    """The sample standard deviation, as the specification requires, not the population one."""
    values = [0.042, 0.044, 0.041]
    runs = [aggregate_run("text_a", i, make_deltas([v])) for i, v in enumerate(values, start=1)]
    result = aggregate_creation("text_a", runs)

    assert result.score_std == pytest.approx(statistics.stdev(values))
    assert result.score_std != pytest.approx(statistics.pstdev(values))


def test_a_single_run_has_no_standard_deviation() -> None:
    """``None`` rather than 0.0: zero would claim a confidence one run cannot support."""
    result = aggregate_creation("text_a", [aggregate_run("text_a", 1, make_deltas([0.3]))])

    assert result.score == pytest.approx(0.3)
    assert result.score_std is None


def test_runs_that_produced_no_score_are_skipped_and_flagged() -> None:
    """Two good runs and one dead one average over the two, and say so."""
    runs = [
        aggregate_run("text_a", 1, make_deltas([0.2])),
        aggregate_run("text_a", 2, make_deltas([0.0], status=ChunkStatus.FAILED)),
        aggregate_run("text_a", 3, make_deltas([0.4])),
    ]
    result = aggregate_creation("text_a", runs)

    assert result.score == pytest.approx(0.3)
    assert result.n_runs_scored == 2
    assert result.unreliable is True
    assert "2 of 3 runs" in result.unreliable_reason


def test_a_creation_with_no_usable_chunk_anywhere_is_unscorable() -> None:
    """Reported with a reason rather than producing a NaN that would move the threshold."""
    runs = [
        aggregate_run("text_a", i, make_deltas([0.0, 0.0], status=ChunkStatus.FAILED))
        for i in (1, 2, 3)
    ]
    result = aggregate_creation("text_a", runs)

    assert result.score is None
    assert result.scorable is False
    assert result.unreliable is True
    assert result.unreliable_reason


def test_exceeding_the_failed_chunk_fraction_marks_the_score_unreliable() -> None:
    """The book's threshold on how much of a creation may be missing before its score is doubted."""
    deltas = [ChunkDelta("text_a", i, 0.2, 400, ChunkStatus.OK) for i in range(90)]
    deltas += [ChunkDelta("text_a", 90 + i, 0.0, 400, ChunkStatus.FAILED) for i in range(10)]

    result = aggregate_creation(
        "text_a", [aggregate_run("text_a", 1, deltas)], max_failed_fraction=0.02
    )

    assert result.score == pytest.approx(0.2)
    assert result.unreliable is True
    assert "failed-chunk fraction" in result.unreliable_reason


def test_within_tolerance_failures_do_not_mark_the_score_unreliable() -> None:
    """One failure in a hundred chunks is below the 2 percent bound and is not flagged."""
    deltas = [ChunkDelta("text_a", i, 0.2, 400, ChunkStatus.OK) for i in range(99)]
    deltas += [ChunkDelta("text_a", 99, 0.0, 400, ChunkStatus.FAILED)]

    result = aggregate_creation(
        "text_a", [aggregate_run("text_a", 1, deltas)], max_failed_fraction=0.02
    )

    assert result.unreliable is False


# ---------------------------------------------------------------------- selection for thresholding


def test_unscorable_creations_are_withheld_from_the_threshold() -> None:
    """They still appear in the report, but they must not influence tau."""
    good = aggregate_creation("text_b", [aggregate_run("text_b", 1, make_deltas([0.2]))])
    dead = aggregate_creation(
        "text_a", [aggregate_run("text_a", 1, make_deltas([0.0], status=ChunkStatus.FAILED))]
    )

    ids, scores = scorable_scores([good, dead])

    assert ids == ["text_b"]
    assert scores == pytest.approx([0.2])
    assert not any(math.isnan(s) for s in scores)


def test_selection_order_is_stable_and_independent_of_input_order() -> None:
    """Ordering must not depend on dictionary or filesystem order, or runs stop being reproducible."""
    creations = [
        aggregate_creation(name, [aggregate_run(name, 1, make_deltas([0.1]))])
        for name in ("text_c", "text_a", "text_b")
    ]

    assert scorable_scores(creations)[0] == ["text_a", "text_b", "text_c"]
    assert scorable_scores(list(reversed(creations)))[0] == ["text_a", "text_b", "text_c"]
