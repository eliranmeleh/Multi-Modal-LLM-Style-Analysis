"""The result artifacts, produced from synthetic scores.

M4's acceptance criterion asks that ``scores.csv``, ``threshold.json`` and the scatter figure are
produced end to end without any of the LLM machinery existing yet.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmlsa.pipeline.classify import classify, compute_threshold
from mmlsa.pipeline.score import (
    ChunkDelta,
    ChunkStatus,
    aggregate_creation,
    aggregate_run,
    scorable_scores,
)
from mmlsa.reporting.plots import histogram, run_variance, sorted_scatter
from mmlsa.reporting.tables import (
    scores_frame,
    suspicious_table,
    write_scores_csv,
    write_threshold_json,
)

SYNTHETIC = {
    "text_a": [0.041, 0.043, 0.042],
    "text_b": [0.048, 0.050, 0.049],
    "text_c": [0.052, 0.051, 0.053],
    "text_d": [0.191, 0.195, 0.193],
    "text_e": [0.205, 0.209, 0.207],
}


@pytest.fixture
def scored() -> list:
    """Five creations with three runs each: three low, two clearly high."""
    creations = []
    for creation_id, per_run in SYNTHETIC.items():
        runs = [
            aggregate_run(
                creation_id,
                run_index,
                [ChunkDelta(creation_id, i, value, 400, ChunkStatus.OK) for i in range(5)],
            )
            for run_index, value in enumerate(per_run, start=1)
        ]
        creations.append(aggregate_creation(creation_id, runs))
    return creations


def test_the_full_offline_chain_produces_every_artifact(scored: list, tmp_path: Path) -> None:
    """Aggregate, threshold, classify, write. No provider involved anywhere in this path."""
    ids, scores = scorable_scores(scored)
    threshold = compute_threshold(scores)
    classification = classify(ids, scores, threshold)

    frame = scores_frame(scored, classification)
    csv_path = write_scores_csv(frame, tmp_path / "scores.csv")
    json_path = write_threshold_json(threshold, classification, tmp_path / "threshold.json")
    scatter_path = sorted_scatter(
        ids, scores, threshold, tmp_path / "figures" / "sorted_scatter.png"
    )
    histogram_path = histogram(scores, threshold, tmp_path / "figures" / "histogram.png")
    variance_path = run_variance(
        [c.creation_id for c in scored],
        [c.per_run for c in scored],
        tmp_path / "figures" / "run_variance.png",
    )

    for path in (csv_path, json_path, scatter_path, histogram_path, variance_path):
        assert path.is_file()
        assert path.stat().st_size > 0


def test_the_synthetic_case_separates_as_intended(scored: list) -> None:
    """The fixture has a known answer; if this fails the fixture is wrong, not the code."""
    ids, scores = scorable_scores(scored)
    threshold = compute_threshold(scores)
    classification = classify(ids, scores, threshold)

    assert classification.suspicious == ["text_d", "text_e"]
    assert classification.authentic == ["text_a", "text_b", "text_c"]
    assert not threshold.flagged


def test_scores_csv_has_one_column_per_run_and_the_summary_columns(scored: list) -> None:
    """The layout named in docs/ARCHITECTURE.md section 6."""
    frame = scores_frame(scored)

    for column in ("creation_id", "n_chunks", "score_mean", "score_std", "s_1", "s_2", "s_3"):
        assert column in frame.columns
    assert len(frame) == len(SYNTHETIC)
    assert list(frame["creation_id"]) == sorted(SYNTHETIC)


def test_unscorable_creations_appear_in_the_table_with_their_reason() -> None:
    """A creation that produced no score must be visible in the output, not silently absent."""
    dead = aggregate_creation(
        "text_z",
        [aggregate_run("text_z", 1, [ChunkDelta("text_z", 0, 0.0, 400, ChunkStatus.FAILED)])],
    )
    frame = scores_frame([dead])

    assert list(frame["creation_id"]) == ["text_z"]
    assert (
        frame.loc[0, "score_mean"] is None
        or frame.loc[0, "score_mean"] != frame.loc[0, "score_mean"]
    )
    assert frame.loc[0, "unreliable"]
    assert frame.loc[0, "unreliable_reason"]


def test_threshold_json_records_the_flags_even_when_empty(scored: list, tmp_path: Path) -> None:
    """The absence of a warning is recorded as a fact, not inferred from a missing key."""
    ids, scores = scorable_scores(scored)
    threshold = compute_threshold(scores)
    classification = classify(ids, scores, threshold)

    path = write_threshold_json(threshold, classification, tmp_path / "threshold.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["method"] == "otsu_exact"
    assert payload["flagged"] is False
    assert payload["diagnostics"]["flags"] == []
    assert payload["suspicious"] == ["text_d", "text_e"]
    assert payload["n_suspicious"] == 2


def test_threshold_json_is_serializable_with_numpy_values(scored: list, tmp_path: Path) -> None:
    """The diagnostics carry numpy scalars; the writer must not choke on them."""
    ids, scores = scorable_scores(scored)
    threshold = compute_threshold(scores)
    classification = classify(ids, scores, threshold)

    path = write_threshold_json(threshold, classification, tmp_path / "threshold.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert isinstance(payload["diagnostics"]["separability"], float)
    assert isinstance(payload["diagnostics"]["n_candidate_splits"], int)


def test_suspicious_table_is_sorted_by_score_descending(scored: list) -> None:
    """The report lists the strongest cases first."""
    ids, scores = scorable_scores(scored)
    threshold = compute_threshold(scores)
    classification = classify(ids, scores, threshold)

    table = suspicious_table(scores_frame(scored, classification))

    assert list(table["creation_id"]) == ["text_e", "text_d"]
