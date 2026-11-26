"""The judgements of the final report (M15) on hand-made labels: no provider, no run directories."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmlsa.reporting.release import used_cache_keys
from mmlsa.reporting.report import cohens_kappa, consensus_agreement, prior_agreement

CASES = {
    "min_correct": 2,
    "expected_label": "suspicious",
    "cases": [
        {"id": "a", "co_author": "X", "citation": "c1"},
        {"id": "b", "co_author": "Y", "citation": "c2"},
        {"id": "z", "co_author": "Z", "citation": "c3"},
    ],
}


def test_consensus_passes_with_enough_cases_right() -> None:
    labels = {"a": "suspicious", "b": "suspicious", "c": "authentic"}
    result = consensus_agreement(labels, {"a": 0.9, "b": 0.8}, CASES)
    assert (result.n_correct, result.n_cases, result.verdict) == (2, 3, "pass")
    (missing,) = [row for row in result.rows if row["creation_id"] == "z"]
    assert missing["label"] == "not in run" and not missing["correct"]


def test_consensus_fails_below_the_minimum() -> None:
    result = consensus_agreement({"a": "suspicious", "b": "authentic"}, {}, CASES)
    assert (result.n_correct, result.verdict) == (1, "fail")


def test_a_complete_prior_list_reads_unnamed_works_as_authentic() -> None:
    labels = {"a": "suspicious", "b": "authentic", "c": "suspicious", "d": "authentic"}
    result = prior_agreement(labels, {"complete": True, "flagged": ["a", "b"]})
    assert result.counts == {
        "both_suspicious": 1,
        "both_authentic": 1,
        "only_ours": 1,
        "only_prior": 1,
    }
    assert result.kappa == pytest.approx(0.0)


def test_an_incomplete_prior_list_compares_only_what_it_names() -> None:
    labels = {"a": "suspicious", "b": "authentic", "c": "suspicious"}
    result = prior_agreement(labels, {"complete": False, "flagged": ["a", "b"]})
    by_id = {row["creation_id"]: row for row in result.rows}
    assert by_id["c"]["prior"] == "unknown" and by_id["c"]["agree"] is None
    assert result.counts["only_ours"] == 0  # c is not counted against the prior study
    assert (result.counts["both_suspicious"], result.counts["only_prior"]) == (1, 1)
    assert result.kappa is None


def test_kappa_matches_a_worked_example() -> None:
    # observed 0.8, chance 0.58, so kappa = 0.22 / 0.42
    counts = {"both_suspicious": 2, "only_ours": 1, "only_prior": 1, "both_authentic": 6}
    assert cohens_kappa(counts) == pytest.approx(0.22 / 0.42)


def test_kappa_is_undefined_without_data_or_variation() -> None:
    empty = dict.fromkeys(("both_suspicious", "only_ours", "only_prior", "both_authentic"), 0)
    assert cohens_kappa(empty) is None
    assert cohens_kappa(empty | {"both_authentic": 5}) is None


def test_the_release_keeps_every_answered_call_once(tmp_path: Path) -> None:
    entries = [
        {"cache_key": "k1", "error": ""},
        {"cache_key": "k2", "error": "PermanentProviderError: refused"},
        {"cache_key": "k1", "error": "", "cached": True},
        {"cache_key": "k3", "error": ""},
    ]
    (tmp_path / "calls.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )
    assert used_cache_keys(tmp_path) == ["k1", "k3"]
