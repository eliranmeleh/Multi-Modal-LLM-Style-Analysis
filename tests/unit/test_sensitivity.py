"""The analysis of Stage 2 (M11) on hand-made scores: no provider, no run directories."""

from __future__ import annotations

import pytest

from mmlsa.experiments.sensitivity import (
    MemberScores,
    SensitivityError,
    chunk_cvs,
    m_rows,
    member_config,
    p_sweep_rows,
    plan_sweep,
    recommend_m,
    stability_rows,
    threshold_labels,
    verdict,
)
from mmlsa.settings import build_config
from tests.conftest import CONFIGS_DIR


@pytest.fixture
def config():
    return build_config(
        CONFIGS_DIR / "mini.yaml",
        set_options=["run.M=3", "experiment.sensitivity.M_values=[1,3]"],
    )


def member(per_run: dict[str, list[float | None]], size: int = 120, **extra) -> MemberScores:
    scores = {
        name: sum(v for v in values if v is not None) / max(1, sum(v is not None for v in values))
        for name, values in per_run.items()
    }
    labels = extra.pop("label", dict.fromkeys(per_run, "authentic"))
    return MemberScores(
        P=size,
        run_id=f"sweep-P{size}",
        tau=0.5,
        per_run=per_run,
        score=scores,
        label=labels,
        borderline=extra.pop("borderline", set()),
        chunk_deltas=extra.pop("chunk_deltas", {}),
    )


# ------------------------------------------------------------------------------- thresholds


def test_labels_follow_the_configured_threshold(config) -> None:
    tau, labels, near = threshold_labels({"a": 0.1, "b": 0.12, "c": 0.9, "d": None}, config)
    assert tau is not None and 0.12 <= tau < 0.9
    assert labels == {"a": "authentic", "b": "authentic", "c": "suspicious", "d": "unscored"}
    assert near == set()


def test_fewer_than_two_scores_cannot_be_thresholded(config) -> None:
    assert threshold_labels({"a": 0.1, "b": None}, config) == (
        None,
        {"a": "unscored", "b": "unscored"},
        set(),
    )


# ----------------------------------------------------------------------------- (a) the runs


STABLE = {"a": [0.10, 0.11, 0.10], "b": [0.12, 0.10, 0.11], "c": [0.90, 0.85, 0.88]}


def test_stable_runs_keep_every_label(config) -> None:
    rows, taus = stability_rows(member(STABLE), config, set())
    assert [row["labels"] for row in rows] == ["a a a", "a a a", "s s s"]
    assert not any(row["label_changed"] for row in rows)
    assert len(taus) == 3
    assert verdict(rows) == ("pass", [], 3)


def test_a_creation_that_flips_between_runs_fails(config) -> None:
    flipping = {**STABLE, "b": [0.12, 0.80, 0.11]}
    rows, _ = stability_rows(member(flipping), config, set())
    (b,) = [row for row in rows if row["creation_id"] == "b"]
    assert b["labels"] == "a s a" and b["label_changed"]
    assert verdict(rows) == ("fail", ["b"], 3)


def test_an_exempt_creation_may_flip(config) -> None:
    flipping = {**STABLE, "b": [0.12, 0.80, 0.11]}
    rows, _ = stability_rows(member(flipping), config, {"b"})
    assert verdict(rows) == ("pass", [], 2)


def test_the_row_carries_mean_sd_and_cv(config) -> None:
    rows, _ = stability_rows(member({"a": [1.0, 2.0, 3.0], "b": [9.0, 9.0, 9.0]}), config, set())
    a = rows[0]
    assert (a["mean"], a["sd"], a["cv"]) == (2.0, 1.0, 0.5)


def test_nothing_judged_is_undefined() -> None:
    assert verdict([{"creation_id": "a", "borderline": True, "exempt": False}]) == (
        "undefined",
        [],
        0,
    )


def test_chunk_cvs_leave_failed_runs_out() -> None:
    scores = member(STABLE, chunk_deltas={("a", 0): [0.2, None, 0.2], ("a", 1): [0.1, 0.3, None]})
    assert chunk_cvs(scores) == [0.0, pytest.approx(0.7071067811865476)]


# ------------------------------------------------------------------------------------ the M


def test_m_rows_compare_the_first_m_runs_with_all(config) -> None:
    drifting = {"a": [0.80, 0.10, 0.10], "b": [0.12, 0.10, 0.11], "c": [0.90, 0.85, 0.88]}
    rows = m_rows(member(drifting), config, set())
    first, full = rows
    assert (first["M"], first["agrees"], first["changed"]) == (1, False, "a")
    assert (full["M"], full["agrees"]) == (3, True)


def test_the_cheapest_agreeing_m_is_recommended() -> None:
    table = [{"M": 3, "agrees": True}, {"M": 5, "agrees": True}]
    assert recommend_m(table, 0.02, 0.1, 5).startswith("M = 3")


def test_too_many_unstable_chunks_say_raise_m() -> None:
    table = [{"M": 3, "agrees": True}]
    assert recommend_m(table, 0.25, 0.1, 5).startswith("raise M above 5")


def test_no_agreeing_m_keeps_the_full_m() -> None:
    assert recommend_m([{"M": 3, "agrees": False}], None, 0.1, 5).startswith("keep M = 5")


# -------------------------------------------------------------------------------- (b) the P


def test_the_p_sweep_flags_a_label_that_changes_with_p() -> None:
    small = member({"a": [0.1], "b": [0.9]}, size=200, label={"a": "authentic", "b": "suspicious"})
    large = member({"a": [0.1], "b": [0.2]}, size=400, label={"a": "authentic", "b": "authentic"})
    rows = p_sweep_rows([small, large], set())
    assert rows[1]["label_P200"] == "suspicious" and rows[1]["label_P400"] == "authentic"
    assert verdict(rows) == ("fail", ["b"], 2)


def test_borderline_at_any_p_is_left_out() -> None:
    small = member({"b": [0.9]}, size=200, label={"b": "suspicious"}, borderline={"b"})
    large = member({"b": [0.2]}, size=400, label={"b": "authentic"})
    assert verdict(p_sweep_rows([small, large], set())) == ("undefined", [], 0)


# ----------------------------------------------------------------------------------- set up


def test_a_member_differs_only_in_p(config) -> None:
    other = member_config(config, 200)
    assert other.chunking.P == 200
    assert other.to_dict() | {"chunking": config.to_dict()["chunking"]} == config.to_dict()


def test_the_reference_p_must_be_swept(config) -> None:
    config.experiment.sensitivity.P_values = [200, 300]
    with pytest.raises(SensitivityError, match=r"reference chunking\.P"):
        plan_sweep(config, "sweep")


def test_no_m_value_may_exceed_the_runs(config) -> None:
    config.experiment.sensitivity.M_values = [3, 5]
    config.experiment.sensitivity.P_values = [config.chunking.P]
    with pytest.raises(SensitivityError, match=r"exceed run\.M"):
        plan_sweep(config, "sweep")
