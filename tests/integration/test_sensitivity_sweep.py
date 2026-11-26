"""Stage 2 end to end on the mini corpus, with the fake provider (M11).

The fake provider gives the same answer in every run, so the numbers say nothing about stability.
What is checked: one ordinary run per ``P``, the tables and verdict written beside them, a sweep that
resumes without redoing a finished ``P``, and a finished sweep that is never overwritten (R9).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mmlsa.cli import app
from mmlsa.experiments.sensitivity import SensitivityError, member_run_id, plan_sweep, run_sweep
from mmlsa.pipeline.orchestrator import execute_run
from mmlsa.settings import build_config
from tests.conftest import CONFIGS_DIR

SWEEP = [
    "run.M=3",
    "noise.enabled=false",  # the mini noise pool holds one text, too few for three runs
    "experiment.sensitivity.P_values=[80,120]",
    "experiment.sensitivity.M_values=[2,3]",
]


def options(tmp_path: Path) -> list[str]:
    return [
        f"run.out_dir={(tmp_path / 'runs').as_posix()}",
        f"llm.cache_dir={(tmp_path / 'cache').as_posix()}",
        *SWEEP,
    ]


@pytest.fixture
def config(tmp_path: Path):
    return build_config(CONFIGS_DIR / "mini.yaml", set_options=options(tmp_path))


def test_the_sweep_runs_once_per_p_and_writes_its_tables(config, tmp_path: Path) -> None:
    result = run_sweep(config, "sweep", progress=False)

    runs = tmp_path / "runs"
    assert sorted(path.name for path in runs.iterdir()) == ["sweep", "sweep-P120", "sweep-P80"]
    for name in ("stability.csv", "m_check.csv", "p_sweep.csv", "chunk_cv.csv", "summary.md"):
        assert (result.sweep_dir / name).is_file(), name
    with (result.sweep_dir / "p_sweep.csv").open(encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    assert {"label_P80", "label_P120"} <= set(header)
    saved = json.loads((result.sweep_dir / "sensitivity.json").read_text(encoding="utf-8"))
    assert saved["verdict"] == result.verdict
    assert saved["details"]["runs"] == {"80": "sweep-P80", "120": "sweep-P120"}


def test_same_answers_in_every_run_are_stable(config) -> None:
    result = run_sweep(config, "sweep", progress=False)
    assert result.stability.startswith("pass: 0 of")
    assert result.recommendation.startswith("M = 2")


def test_a_sweep_resumes_without_redoing_a_finished_p(config, tmp_path: Path) -> None:
    from mmlsa.experiments.sensitivity import member_config

    first = execute_run(
        member_config(config, 80), run_id=member_run_id("sweep", 80), progress=False
    )
    finished = (first.run_dir / "manifest.json").stat().st_mtime_ns

    run_sweep(config, "sweep", progress=False)

    assert (first.run_dir / "manifest.json").stat().st_mtime_ns == finished


def test_a_finished_sweep_is_never_overwritten(config) -> None:
    run_sweep(config, "sweep", progress=False)
    with pytest.raises(SensitivityError, match="already complete"):
        run_sweep(config, "sweep", progress=False)


def test_the_plan_prices_each_p_and_sends_nothing(tmp_path: Path) -> None:
    arguments = ["experiment", "sensitivity", "--config", str(CONFIGS_DIR / "mini.yaml")]
    for option in options(tmp_path):
        arguments += ["--set", option]
    outcome = CliRunner().invoke(app, arguments)

    assert outcome.exit_code == 0, outcome.output
    assert "P = 80" in outcome.output and "P = 120" in outcome.output
    assert "Nothing was requested" in outcome.output
    assert not (tmp_path / "runs").exists()


def test_the_plan_counts_every_run(config) -> None:
    plan = plan_sweep(config, "sweep")
    assert [size for size, _ in plan.members] == [80, 120]
    assert all(member.n_runs == 3 for _, member in plan.members)
