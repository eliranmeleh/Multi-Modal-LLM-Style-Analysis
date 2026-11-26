"""The deterministic parts of the four validation checks (M14): no provider, no files."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from mmlsa.chunking import chunk_text
from mmlsa.experiments.validation import (
    Baseline,
    CheckError,
    calibration_verdict,
    choose_targets,
    coefficient_of_variation,
    compare_labels,
    label_for,
    mean_by_chunk,
    method_differences,
    peak_chunk,
    splice_text,
)

# ------------------------------------------------------------------------------------- calibration


def test_cv_is_the_sample_sd_over_the_mean() -> None:
    assert coefficient_of_variation([1.0, 2.0, 3.0]) == pytest.approx(0.5)


def test_identical_deltas_have_no_spread() -> None:
    assert coefficient_of_variation([0.2, 0.2, 0.2]) == 0.0


def test_all_zero_deltas_are_stable_not_undefined() -> None:
    assert coefficient_of_variation([0.0, 0.0]) == 0.0


def test_fewer_than_two_deltas_measure_nothing() -> None:
    assert coefficient_of_variation([0.3]) is None
    assert coefficient_of_variation([]) is None


def test_calibration_passes_at_the_bound() -> None:
    cvs = [0.0] * 9 + [0.5]
    assert calibration_verdict(cvs, max_cv=0.15, min_share=0.9) == ("pass", 9, 10, 0.9)


def test_calibration_fails_below_the_bound() -> None:
    verdict, stable, measured, share = calibration_verdict([0.0, 0.5], max_cv=0.15, min_share=0.9)
    assert (verdict, stable, measured, share) == ("fail", 1, 2, 0.5)


def test_unmeasured_chunks_are_left_out_of_the_share() -> None:
    assert calibration_verdict([0.1, None, None], 0.15, 0.9) == ("pass", 1, 1, 1.0)


def test_calibration_with_nothing_measured_is_undefined() -> None:
    assert calibration_verdict([None, None], 0.15, 0.9) == ("undefined", 0, 0, None)


# ----------------------------------------------------------------------------------------- mixture

TARGET = " ".join(f"t{i}" for i in range(100))
SOURCE = " ".join(f"s{i}" for i in range(50))


def test_a_splice_keeps_the_length_and_every_other_word() -> None:
    text, record = splice_text(
        TARGET, SOURCE, 20, random.Random(7), 30, target_id="a", source_id="b"
    )
    words, original = text.split(), TARGET.split()
    assert len(words) == len(original)
    start = record.start
    assert words[:start] == original[:start]
    assert words[start + 20 :] == original[start + 20 :]
    assert (
        words[start : start + 20] == SOURCE.split()[record.source_start : record.source_start + 20]
    )


def test_a_splice_records_the_chunks_it_touches() -> None:
    text, record = splice_text(
        TARGET, SOURCE, 20, random.Random(7), 30, target_id="a", source_id="b"
    )
    changed = [
        chunk.index
        for chunk, before in zip(chunk_text(text, 30), chunk_text(TARGET, 30), strict=True)
        if chunk.text != before.text
    ]
    assert changed == list(range(record.first_chunk, record.last_chunk + 1))
    assert record.creation_id == "a__b"


def test_a_splice_is_seeded() -> None:
    first = splice_text(TARGET, SOURCE, 20, random.Random(3), 30)
    second = splice_text(TARGET, SOURCE, 20, random.Random(3), 30)
    assert first == second


def test_a_splice_must_fit_in_the_target() -> None:
    with pytest.raises(CheckError, match="does not fit"):
        splice_text("a b c", SOURCE, 3, random.Random(0), 10, target_id="short")


def test_a_splice_cannot_take_more_than_the_source_has() -> None:
    with pytest.raises(CheckError, match="has only 50 words"):
        splice_text(TARGET, SOURCE, 60, random.Random(0), 10, source_id="src")


def test_chunk_means_skip_failed_runs() -> None:
    assert mean_by_chunk([[0.1, 0.3], [None, 0.4], [None, None]]) == [
        pytest.approx(0.2),
        0.4,
        None,
    ]


def test_the_peak_is_the_highest_mean_and_the_first_on_a_tie() -> None:
    assert peak_chunk([0.1, None, 0.5, 0.5, 0.2]) == 2
    assert peak_chunk([None, None]) is None
    assert peak_chunk([0.0, 0.0]) == 0


def baseline(scores: dict[str, float | None], labels: dict[str, str], borderline=()) -> Baseline:
    return Baseline(
        run_id="base",
        run_dir=Path(),
        M=1,
        tau=0.5,
        profiles={1: "p"},
        scores=scores,
        labels=labels,
        borderline=frozenset(borderline),
    )


def test_targets_are_the_lowest_scoring_clear_authentic_creations() -> None:
    chosen = choose_targets(
        baseline(
            {"a": 0.30, "b": 0.10, "c": 0.20, "d": 0.90, "e": 0.05, "f": None},
            {
                "a": "authentic",
                "b": "authentic",
                "c": "authentic",
                "d": "suspicious",
                "e": "authentic",
                "f": "unscored",
            },
            borderline={"e"},
        ),
        None,
        2,
    )
    assert chosen == ["b", "c"]


def test_configured_targets_must_be_in_the_baseline() -> None:
    with pytest.raises(CheckError, match="not in the baseline"):
        choose_targets(baseline({"a": 0.1}, {"a": "authentic"}), ["zzz"], 1)


def test_no_clear_authentic_creation_is_an_error() -> None:
    with pytest.raises(CheckError, match="clearly authentic"):
        choose_targets(baseline({"a": 0.9}, {"a": "suspicious"}), None, 1)


# ------------------------------------------------------------------------------- labels and runs


def test_labels_follow_step_6() -> None:
    assert label_for(0.6, 0.5, 0.01) == ("suspicious", False)
    assert label_for(0.5, 0.5, 0.01) == ("authentic", True)
    assert label_for(0.495, 0.5, 0.01) == ("authentic", True)
    assert label_for(None, 0.5, 0.01) == ("unscored", False)


def test_borderline_creations_are_left_out_of_the_noise_comparison() -> None:
    compared, changed, skipped = compare_labels(
        {"a": "authentic", "b": "suspicious", "c": "authentic"},
        {"a": "authentic", "b": "authentic", "c": "suspicious"},
        {"c"},
    )
    assert (compared, changed, skipped) == (["a", "b"], ["b"], ["c"])


def test_experiment_and_rate_keys_may_differ_from_the_baseline() -> None:
    before = {
        "experiment": {"mixture": {"n_splices": 3}},
        "llm": {"mode": "live", "concurrency": 1},
    }
    after = {
        "experiment": {"mixture": {"n_splices": 1}},
        "llm": {"mode": "replay", "concurrency": 8},
    }
    assert method_differences(before, after) == []


def test_method_keys_may_not() -> None:
    before = {"chunking": {"P": 400}, "noise": {"enabled": True}}
    after = {"chunking": {"P": 200}, "noise": {"enabled": False}}
    assert method_differences(before, after) == ["chunking.P", "noise.enabled"]
    assert method_differences(before, after, also_free=("noise",)) == ["chunking.P"]
