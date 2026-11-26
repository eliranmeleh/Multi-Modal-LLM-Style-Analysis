"""The control experiment end to end on the mini corpus, with the fake provider (M13).

The numbers are reproducible but mean nothing, as everywhere the fake provider answers. What is
checked is that both arms run over the same chunks, that every number traces back to its rewrites
and calls (R7), that a re-run costs nothing, and that the artifacts are not overwritten (R9).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mmlsa.cli import app
from mmlsa.experiments.control import ControlError, paired_statistics, plan_control, run_control
from mmlsa.llm.ledger import read_ledger
from mmlsa.pipeline.orchestrator import execute_run
from mmlsa.settings import build_config
from tests.conftest import CONFIGS_DIR

SAMPLE = 6


def mini(tmp_path: Path, *extra: str):
    """The mini configuration with a small control sample, writing under ``tmp_path``."""
    return build_config(
        CONFIGS_DIR / "mini.yaml",
        set_options=[
            f"run.out_dir={(tmp_path / 'runs').as_posix()}",
            f"llm.cache_dir={(tmp_path / 'cache').as_posix()}",
            f"experiment.control.sample_chunks={SAMPLE}",
            *extra,
        ],
    )


@pytest.fixture
def config(tmp_path: Path):
    return mini(tmp_path)


@pytest.fixture
def finished(config):
    return run_control(config, run_id="control-1", progress=False)


def test_the_experiment_writes_its_artifacts(finished) -> None:
    for name in (
        "control.json",
        "pairs.csv",
        "summary.md",
        "manifest.json",
        "calls.jsonl",
        "config.snapshot.yaml",
        "code_version.json",
        "rewrites/mode_a.jsonl",
        "rewrites/mode_b.jsonl",
        "profiles/run_1_merged.json",
        "profiles/run_1_sources.json",
    ):
        assert (finished.run_dir / name).is_file(), f"missing {name}"


def test_both_arms_rewrite_the_same_chunks(finished) -> None:
    keys = [(chunk.creation_id, chunk.index) for chunk in finished.sample]

    assert len(keys) == SAMPLE
    assert [(r.creation_id, r.chunk_index) for r in finished.mode_a] == keys
    assert [(r.creation_id, r.chunk_index) for r in finished.mode_b] == keys


def test_the_ledger_holds_one_profile_and_both_arms(finished) -> None:
    """R2: every call is in the ledger, and the two arms are told apart by their tag."""
    tags = [entry["tag"] for entry in read_ledger(finished.run_dir / "calls.jsonl")]

    assert tags.count("rewrite") >= SAMPLE
    assert tags.count("rewrite_generic") >= SAMPLE
    assert "profile" in tags


def test_mode_b_names_the_configured_author_and_mode_a_does_not(finished, config) -> None:
    """The author's name reaches a prompt in Mode B only, and from configuration (R1)."""
    label = config.corpus.author_label
    entries = read_ledger(finished.run_dir / "calls.jsonl")

    assert all(label in e["prompt"] for e in entries if e["tag"] == "rewrite_generic")
    assert not any(label in e["prompt"] for e in entries if e["tag"] != "rewrite_generic")


def test_the_statistics_trace_back_to_pairs_csv(finished) -> None:
    """R7: recomputing the test from the per-chunk deltas on disk gives the reported result."""
    with (finished.run_dir / "pairs.csv").open(encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["paired"] == "True"]
    recomputed = paired_statistics(
        [float(row["delta_a"]) for row in rows], [float(row["delta_b"]) for row in rows]
    )
    reported = json.loads((finished.run_dir / "control.json").read_text(encoding="utf-8"))

    assert reported["n_paired"] == len(rows)
    assert reported["statistics"] == pytest.approx(recomputed.to_dict())


def test_a_rerun_is_answered_from_the_cache(finished, config) -> None:
    again = run_control(config, run_id="control-2", progress=False)

    assert again.manifest["calls"]["live"] == 0
    assert again.statistics == finished.statistics


def test_a_finished_experiment_is_never_overwritten(finished, config) -> None:
    """R9."""
    with pytest.raises(ControlError, match="immutable"):
        run_control(config, run_id="control-1", progress=False)


def test_a_finished_experiment_reads_as_finished(finished) -> None:
    """Every run directory marks its end the same way, so one check reads them all."""
    from mmlsa.pipeline.orchestrator import is_complete

    assert is_complete(finished.run_dir)


def test_mode_a_reuses_the_answers_of_a_run_over_the_same_corpus(tmp_path: Path) -> None:
    """Mode A asks what run 1 of a run asks, so after a run only Mode B is new."""
    execute_run(mini(tmp_path), progress=False)

    result = run_control(mini(tmp_path), run_id="after-a-run", progress=False)

    entries = read_ledger(result.run_dir / "calls.jsonl")
    live = {entry["tag"] for entry in entries if not entry["cached"]}
    assert live == {"rewrite_generic"}


def test_an_empty_author_label_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ControlError, match="author_label"):
        plan_control(mini(tmp_path, 'corpus.author_label="  "'))


def test_the_plan_counts_one_profile_call_and_two_rewrites_per_chunk(config) -> None:
    plan = plan_control(config)

    assert plan.n_sample == SAMPLE
    assert plan.rewrite_calls == 2 * SAMPLE
    assert plan.total_calls == plan.profile_calls + 2 * SAMPLE


def test_the_command_stops_at_the_plan_without_yes(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "experiment",
            "control",
            "--config",
            str(CONFIGS_DIR / "mini.yaml"),
            "--set",
            f"run.out_dir={(tmp_path / 'runs').as_posix()}",
            "--set",
            f"llm.cache_dir={(tmp_path / 'cache').as_posix()}",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Nothing was requested" in result.stdout
    assert not (tmp_path / "runs").exists()
