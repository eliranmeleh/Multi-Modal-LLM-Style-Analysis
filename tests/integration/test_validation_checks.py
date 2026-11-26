"""The four validation checks end to end on the mini corpus, with the fake provider (M14).

The verdicts mean nothing here, as everywhere the fake provider answers. What is checked is that each
check runs against its baseline, adds calls only for what is new, writes the table behind its number
(R7), never overwrites itself (R9), refuses a baseline it cannot measure, and gives the same answer
when replayed from a recorded bundle, which is how ``pytest tests/validation`` runs it.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from mmlsa.cli import app
from mmlsa.experiments import validation
from mmlsa.experiments.validation import CheckError
from mmlsa.llm.ledger import read_ledger
from mmlsa.pipeline.orchestrator import execute_run
from mmlsa.settings import build_config
from tests.conftest import CONFIGS_DIR
from tests.validation import conftest as replay


def mini(tmp_path: Path, *extra: str):
    """The mini configuration, writing under ``tmp_path``."""
    return build_config(
        CONFIGS_DIR / "mini.yaml",
        set_options=[
            f"run.out_dir={(tmp_path / 'runs').as_posix()}",
            f"llm.cache_dir={(tmp_path / 'cache').as_posix()}",
            *extra,
        ],
    )


@pytest.fixture
def config(tmp_path: Path):
    return mini(tmp_path)


@pytest.fixture
def baseline(config) -> str:
    return execute_run(config, run_id="baseline", progress=False).run_id


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# ----------------------------------------------------------------------------------- calibration


def test_calibration_measures_every_sampled_chunk(config, baseline) -> None:
    result = validation.run_calibration(config, baseline, progress=False)
    sample = config.experiment.calibration.sample_chunks
    table = rows(result.run_dir / "calibration.csv")
    assert len(table) == sample
    assert result.verdict in {"pass", "fail", "undefined"}
    assert result.details["repeats"] == config.experiment.calibration.repeats
    for name in ("calibration.json", "summary.md", "manifest.json", "calls.jsonl"):
        assert (result.run_dir / name).is_file(), name
    repeats = sorted(path.name for path in (result.run_dir / "rewrites").iterdir())
    assert repeats == [f"repeat_{r}.jsonl" for r in range(1, 4)]


def test_repeat_one_is_the_baseline_answer(config, baseline) -> None:
    result = validation.run_calibration(config, baseline, progress=False)
    ledger = read_ledger(result.run_dir / "calls.jsonl")
    sample = config.experiment.calibration.sample_chunks
    first = [entry for entry in ledger if entry["run_index"] == 1]
    second = [entry for entry in ledger if entry["run_index"] == 2]
    assert len(first) == sample and all(entry["cached"] for entry in first)
    assert len(second) == sample and not any(entry["cached"] for entry in second)


# --------------------------------------------------------------------------------------- mixture


def test_mixture_recalls_only_the_spliced_chunks(config, baseline) -> None:
    result = validation.run_mixture(config, baseline, progress=False)
    splice = result.details["splices"][0]
    touched = splice["last_chunk"] - splice["first_chunk"] + 1
    calls = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))["calls"]
    assert calls["live"] == touched * config.run.M
    assert calls["total"] - calls["live"] == calls["cached"]


def test_mixture_reports_the_splice_against_the_baseline(config, baseline) -> None:
    result = validation.run_mixture(config, baseline, progress=False)
    (row,) = rows(result.run_dir / "mixture.csv")
    assert row["target"] == "mini_alpha"  # the baseline's lowest-scoring authentic creation
    assert float(row["tau"]) == pytest.approx(
        json.loads((config.path(config.run.out_dir) / baseline / "threshold.json").read_text())[
            "tau"
        ]
    )
    chunks = rows(result.run_dir / "mixture_chunks.csv")
    assert [c["in_splice"] for c in chunks].count("True") == int(
        result.details["splices"][0]["last_chunk"] - result.details["splices"][0]["first_chunk"] + 1
    )


# -------------------------------------------------------------------------------------- held-out


def test_heldout_scores_every_reserved_text(config, baseline) -> None:
    result = validation.run_heldout(config, baseline, progress=False)
    table = {row["creation_id"]: row for row in rows(result.run_dir / "heldout.csv")}
    assert set(table) == {"mini_heldout_kin", "mini_heldout_stranger"}
    assert table["mini_heldout_stranger"]["expected"] == "suspicious"
    assert result.measured.endswith("of 2 held-out texts classified as expected")


# ----------------------------------------------------------------------------------------- noise


def test_noise_compares_the_two_variants(tmp_path: Path, config, baseline) -> None:
    plain = mini(tmp_path, "noise.enabled=false")
    without = execute_run(plain, run_id="plain", progress=False).run_id
    result = validation.run_noise(config, baseline, without)
    assert result.details["n_compared"] + result.details["n_borderline"] == 3
    assert not (result.run_dir / "calls.jsonl").exists()


def test_noise_refuses_the_runs_the_wrong_way_round(tmp_path: Path, config, baseline) -> None:
    plain = mini(tmp_path, "noise.enabled=false")
    without = execute_run(plain, run_id="plain", progress=False).run_id
    with pytest.raises(CheckError, match="must be the run with noise"):
        validation.run_noise(config, without, baseline)


def test_noise_refuses_runs_that_differ_in_more_than_noise(
    tmp_path: Path, config, baseline
) -> None:
    other = mini(tmp_path, "noise.enabled=false", "chunking.P=100")
    without = execute_run(other, run_id="plain-p100", progress=False).run_id
    with pytest.raises(CheckError, match=r"chunking.P"):
        validation.run_noise(config, baseline, without)


# ------------------------------------------------------------------------------------ guardrails


def test_a_check_refuses_a_different_method(tmp_path: Path, baseline) -> None:
    with pytest.raises(CheckError, match=r"chunking.P"):
        validation.run_heldout(mini(tmp_path, "chunking.P=100"), baseline, progress=False)


def test_a_check_needs_a_finished_baseline(config) -> None:
    with pytest.raises(CheckError, match="no finished run"):
        validation.run_calibration(config, "never-ran", progress=False)


def test_a_check_never_overwrites_itself(config, baseline) -> None:
    validation.run_heldout(config, baseline, progress=False)
    with pytest.raises(CheckError, match="immutable"):
        validation.run_heldout(config, baseline, progress=False)


def test_the_cli_plans_without_calling(tmp_path: Path, baseline) -> None:
    out = (tmp_path / "runs").as_posix()
    outcome = CliRunner().invoke(
        app,
        [
            "experiment",
            "heldout",
            "--config",
            str(CONFIGS_DIR / "mini.yaml"),
            "--baseline",
            baseline,
            "--set",
            f"run.out_dir={out}",
            "--set",
            f"llm.cache_dir={(tmp_path / 'cache').as_posix()}",
        ],
    )
    assert outcome.exit_code == 0, outcome.output
    assert "Nothing was requested" in outcome.output
    assert sorted(path.name for path in (tmp_path / "runs").iterdir()) == ["baseline"]


# -------------------------------------------------------------------------------------- replay


def record(tmp_path: Path, check: str, run_ids: dict[str, str]) -> None:
    """Copy finished runs and the cache into a bundle, as ``docs/RUNBOOK.md`` describes."""
    bundle = tmp_path / "recorded" / check
    for run_id in set(run_ids.values()):
        shutil.copytree(tmp_path / "runs" / run_id, bundle / "runs" / run_id)
    shutil.copytree(tmp_path / "cache", bundle / "cache")
    (bundle / "recording.yaml").write_text(
        yaml.safe_dump({"config": "configs/mini.yaml", "set": [], **run_ids}), encoding="utf-8"
    )


@pytest.mark.parametrize("check", ["calibration", "mixture", "heldout"])
def test_a_recorded_check_replays_to_the_same_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config, baseline, check
) -> None:
    live = getattr(validation, f"run_{check}")(config, baseline, progress=False)
    record(tmp_path, check, {"baseline": baseline})
    monkeypatch.setattr(replay, "RECORDED", tmp_path / "recorded")

    replayed = replay.replay_check(check, tmp_path / "replay", monkeypatch)

    assert replayed.measured == live.measured
    assert replayed.verdict == live.verdict
    ledger = read_ledger(replayed.run_dir / "calls.jsonl")
    assert ledger and all(entry["cached"] for entry in ledger)


def test_a_recorded_noise_check_replays(tmp_path: Path, monkeypatch, config, baseline) -> None:
    without = execute_run(mini(tmp_path, "noise.enabled=false"), run_id="plain", progress=False)
    live = validation.run_noise(config, baseline, without.run_id)
    record(tmp_path, "noise", {"with_noise": baseline, "without_noise": without.run_id})
    monkeypatch.setattr(replay, "RECORDED", tmp_path / "recorded")

    assert replay.replay_check("noise", tmp_path / "replay", monkeypatch).measured == live.measured
