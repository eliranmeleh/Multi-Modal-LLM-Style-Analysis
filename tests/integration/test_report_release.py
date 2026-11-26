"""Report, release and reproduce end to end on the mini corpus, with the fake provider (M15).

The acceptance test of M15 is here in miniature: a run is packed into a release, the release is
unpacked into an empty folder with no other cache, and replaying the run from it gives the same
``scores.csv`` and ``threshold.json`` byte for byte.
"""

from __future__ import annotations

import csv
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mmlsa.cli import app
from mmlsa.experiments import validation
from mmlsa.llm.ledger import read_ledger
from mmlsa.pipeline.orchestrator import execute_run
from mmlsa.reporting.release import ReleaseError, build_release, reproduce_run
from mmlsa.reporting.report import ReportError, build_report
from mmlsa.settings import build_config
from tests.conftest import CONFIGS_DIR


def options(runs: Path, cache: Path) -> list[str]:
    return [f"run.out_dir={runs.as_posix()}", f"llm.cache_dir={cache.as_posix()}"]


def mini(runs: Path, cache: Path):
    return build_config(CONFIGS_DIR / "mini.yaml", set_options=options(runs, cache))


@pytest.fixture
def config(tmp_path: Path):
    return mini(tmp_path / "runs", tmp_path / "cache")


@pytest.fixture
def run_id(config) -> str:
    return execute_run(config, run_id="final", progress=False).run_id


# ---------------------------------------------------------------------------------------- report


def test_the_report_carries_every_section(tmp_path: Path, config, run_id) -> None:
    built = build_report(config, run_id, out_dir=tmp_path / "report")

    text = (built.out_dir / "report.md").read_text(encoding="utf-8")
    for heading in (
        "## The threshold",
        "## Scores",
        "## Success metric 1",
        "## Success metric 3",
        "## Agreement with the prior study",
        "## The injected noise texts",
    ):
        assert heading in text, heading
    for name in ("scores.csv", "stability.csv", "consensus.csv", "prior_agreement.csv"):
        assert (built.out_dir / name).is_file(), name
    assert (built.out_dir / "figures" / "sorted_scatter.png").is_file()
    assert built.prior.complete and built.prior.kappa is not None
    assert built.consensus.n_cases == 1


def test_the_report_agrees_with_the_run(tmp_path: Path, config, run_id) -> None:
    built = build_report(config, run_id, out_dir=tmp_path / "report")
    with (config.path(config.run.out_dir) / run_id / "scores.csv").open(encoding="utf-8") as handle:
        labels = {row["creation_id"]: row["label"] for row in csv.DictReader(handle)}
    (row,) = built.consensus.rows
    assert row["label"] == labels["mini_beta"]


def test_the_report_never_writes_into_the_run(tmp_path: Path, config, run_id) -> None:
    run_dir = config.path(config.run.out_dir) / run_id
    before = sorted(path.relative_to(run_dir) for path in run_dir.rglob("*"))
    build_report(config, run_id, out_dir=tmp_path / "report")
    assert sorted(path.relative_to(run_dir) for path in run_dir.rglob("*")) == before


def test_the_report_lists_an_included_experiment(tmp_path: Path, config, run_id) -> None:
    check = validation.run_heldout(config, run_id, progress=False)
    built = build_report(config, run_id, out_dir=tmp_path / "report", include=[check.run_id])
    (line,) = built.experiments
    assert (line["experiment"], line["verdict"]) == ("heldout", check.verdict)
    assert "## Experiments on this run" in (built.out_dir / "report.md").read_text(encoding="utf-8")


def test_the_report_needs_a_finished_run(tmp_path: Path, config) -> None:
    with pytest.raises(ReportError, match="not a finished run"):
        build_report(config, "never-ran", out_dir=tmp_path / "report")


# --------------------------------------------------------------------------- release, reproduce


def test_a_release_holds_the_run_and_only_its_answers(tmp_path: Path, config, run_id) -> None:
    packed = build_release(config, [run_id], out_dir=tmp_path / "release")

    with tarfile.open(packed.archive) as tar:
        names = tar.getnames()
    keys = {entry["cache_key"] for entry in read_ledger(tmp_path / "runs" / run_id / "calls.jsonl")}
    cached = {Path(name).stem for name in names if name.startswith("cache/")}
    assert cached == keys and packed.n_cache_entries == len(keys)
    assert f"runs/{run_id}/scores.csv" in names and "RELEASE.md" in names
    digest = (tmp_path / "release" / f"{packed.archive.name}.sha256").read_text(encoding="utf-8")
    assert digest.startswith(packed.sha256)


def test_a_release_refuses_a_missing_answer(tmp_path: Path, config, run_id) -> None:
    next((tmp_path / "cache").rglob("*.json")).unlink()
    with pytest.raises(ReleaseError, match="not in"):
        build_release(config, [run_id], out_dir=tmp_path / "release")


def test_a_release_is_never_overwritten(tmp_path: Path, config, run_id) -> None:
    build_release(config, [run_id], out_dir=tmp_path / "release")
    with pytest.raises(ReleaseError, match="never overwritten"):
        build_release(config, [run_id], out_dir=tmp_path / "release")


def test_a_released_run_reproduces_byte_for_byte_from_the_archive_alone(
    tmp_path: Path, config, run_id
) -> None:
    packed = build_release(config, [run_id], out_dir=tmp_path / "release")
    clean = tmp_path / "clean"
    with tarfile.open(packed.archive) as tar:
        tar.extractall(clean, filter="data")

    outcome = reproduce_run(
        mini(clean / "runs", clean / "cache"), run_id, out_dir=tmp_path / "replayed"
    )

    assert outcome.matches == {"scores.csv": True, "threshold.json": True}
    ledger = read_ledger(outcome.replay_dir / "calls.jsonl")
    assert ledger and all(entry["cached"] for entry in ledger)


def test_a_changed_result_is_caught(tmp_path: Path, config, run_id) -> None:
    scores = tmp_path / "runs" / run_id / "scores.csv"
    scores.write_text(scores.read_text(encoding="utf-8").replace("0.0", "0.1", 1), encoding="utf-8")
    outcome = reproduce_run(config, run_id, out_dir=tmp_path / "replayed")
    assert outcome.matches["scores.csv"] is False and not outcome.identical


def test_replay_never_calls_for_a_missing_answer(tmp_path: Path, config, run_id) -> None:
    next((tmp_path / "cache").rglob("*.json")).unlink()
    with pytest.raises(Exception, match="cache miss in replay mode"):
        reproduce_run(config, run_id, out_dir=tmp_path / "replayed")


def test_the_cli_reports_a_reproduction(tmp_path: Path, run_id) -> None:
    arguments = ["reproduce", "--run-id", run_id, "--config", str(CONFIGS_DIR / "mini.yaml")]
    arguments += ["--out", str(tmp_path / "replayed")]
    for option in options(tmp_path / "runs", tmp_path / "cache"):
        arguments += ["--set", option]
    outcome = CliRunner().invoke(app, arguments)

    assert outcome.exit_code == 0, outcome.output
    assert "REPRODUCED" in outcome.output
    assert (tmp_path / "replayed" / f"{run_id}.reproduction.json").is_file()
