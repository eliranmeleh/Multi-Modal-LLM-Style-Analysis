"""The `M`-run loop, end to end, through the real configuration path.

This is the milestone at which the pipeline is finished. These tests run the whole thing the way a
user would — one command, one configuration file — and check what it leaves behind.

Everything here uses `FakeProvider`, so the *numbers* are reproducible but not meaningful. What is
being checked is that the run happens, that its artifacts are complete and consistent, and that the
properties the specification requires of it actually hold.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from mmlsa.pipeline.orchestrator import RunError, execute_run, is_complete, plan_run
from mmlsa.settings import build_config
from tests.conftest import CONFIGS_DIR


@pytest.fixture
def config(tmp_path: Path):
    """The mini configuration, writing its runs and cache under ``tmp_path``."""
    return build_config(
        CONFIGS_DIR / "mini.yaml",
        set_options=[
            f"run.out_dir={(tmp_path / 'runs').as_posix()}",
            f"llm.cache_dir={(tmp_path / 'cache').as_posix()}",
        ],
    )


@pytest.fixture
def completed(config):
    """One completed run."""
    return execute_run(config, progress=False)


# ---------------------------------------------------------------------------------- the run


def test_a_run_completes_and_classifies_every_creation(completed) -> None:
    """The headline: one command takes the corpus to labels."""
    assert len(completed.creations) == 3
    assert len(completed.classification.labels) == 3
    assert all(creation.scorable for creation in completed.creations)


def test_the_run_directory_matches_the_documented_layout(completed) -> None:
    """docs/ARCHITECTURE.md section 6, checked file by file."""
    run_dir = completed.run_dir

    for name in (
        "manifest.json",
        "config.snapshot.yaml",
        "scores.csv",
        "threshold.json",
        "noise_diagnostics.csv",
        "calls.jsonl",
    ):
        assert (run_dir / name).is_file(), f"missing {name}"

    for directory in ("profiles", "chunks", "rewrites", "deltas", "figures", "logs"):
        assert (run_dir / directory).is_dir(), f"missing {directory}/"

    assert (run_dir / "figures" / "sorted_scatter.png").is_file()
    assert (run_dir / "figures" / "histogram.png").is_file()
    assert (run_dir / "figures" / "run_variance.png").is_file()


def test_artifacts_are_written_for_every_run_and_every_creation(completed, config) -> None:
    """`M` profiles, `M` delta files, and one rewrite file per creation per run."""
    run_dir = completed.run_dir

    for run_index in range(1, config.run.M + 1):
        assert (run_dir / "profiles" / f"run_{run_index}_merged.json").is_file()
        assert (run_dir / "profiles" / f"run_{run_index}_partials.json").is_file()
        assert (run_dir / "profiles" / f"run_{run_index}_packing.json").is_file()
        assert (run_dir / "deltas" / f"run_{run_index}.csv").is_file()
        assert len(list((run_dir / "rewrites" / f"run_{run_index}").glob("*.jsonl"))) >= 3

    assert len(list((run_dir / "chunks").glob("*.jsonl"))) >= 3


def test_the_snapshot_alone_reproduces_the_configuration(completed, config) -> None:
    """ARCHITECTURE 7.1 rule 5: a run is reproducible from its snapshot, with no parent files."""
    from mmlsa.config import load_config

    snapshot = load_config(completed.run_dir / "config.snapshot.yaml")

    assert snapshot.config_hash() == config.config_hash()


# ----------------------------------------------------------------------------- noise injection


def test_the_noise_diagnostic_lists_exactly_m_minus_one_distinct_creations(
    completed, config
) -> None:
    """The acceptance criterion."""
    with (completed.run_dir / "noise_diagnostics.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == config.run.M - 1
    assert len({row["creation_id"] for row in rows}) == len(rows)
    assert all(row["run_index"] != "1" for row in rows)


def test_the_injected_creation_is_scored_but_never_classified(completed) -> None:
    """docs/DECISIONS.md I7: a diagnostic, excluded from tau and from the reported set."""
    with (completed.run_dir / "noise_diagnostics.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    injected = {row["creation_id"] for row in rows}

    assert injected
    assert all(row["score"] for row in rows), "the injected text should be scored"
    assert not injected & set(completed.classification.labels)
    assert not injected & {creation.creation_id for creation in completed.creations}


def test_the_injected_creation_is_chunked_and_rewritten(completed) -> None:
    """It goes through the same path as any other text, so its score means the same thing."""
    with (completed.run_dir / "noise_diagnostics.csv").open(encoding="utf-8") as handle:
        noise_id = next(csv.DictReader(handle))["creation_id"]

    assert (completed.run_dir / "chunks" / f"{noise_id}.jsonl").is_file()
    assert (completed.run_dir / "rewrites" / "run_2" / f"{noise_id}.jsonl").is_file()


def test_run_one_receives_no_noise(completed) -> None:
    """The plain corpus, as specified."""
    assert completed.manifest["noise"]["by_run"].get("1") is None
    assert (completed.run_dir / "rewrites" / "run_1").is_dir()
    assert not list((completed.run_dir / "rewrites" / "run_1").glob("*noise*"))


def test_noise_can_be_disabled(config) -> None:
    """Phase B evaluates the no-added-noise variant as a comparison."""
    from mmlsa.settings import build_config as build

    plain = build(
        CONFIGS_DIR / "mini.yaml",
        set_options=[
            f"run.out_dir={(config.path(config.run.out_dir)).as_posix()}",
            f"llm.cache_dir={(config.path(config.llm.cache_dir)).as_posix()}",
            "noise.enabled=false",
        ],
    )
    result = execute_run(plain, progress=False)

    with (result.run_dir / "noise_diagnostics.csv").open(encoding="utf-8") as handle:
        assert list(csv.DictReader(handle)) == []


# -------------------------------------------------------------------------------- the M runs


def test_each_creation_has_one_score_per_run(completed, config) -> None:
    """`s_1 .. s_M`, which is what Step 5 averages."""
    with (completed.run_dir / "scores.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    for run_index in range(1, config.run.M + 1):
        assert f"s_{run_index}" in rows[0]
    assert all(row["score_mean"] for row in rows)


def test_the_runs_actually_differ(completed) -> None:
    """The property M7 flagged: without it, the averaging is `M` copies of one number.

    Noise injection changes the corpus in run 2, which changes the profile, which changes every
    rewrite prompt. If this fails, the `M`-run machinery is running but measuring nothing.
    """
    per_run_spreads = [
        creation.score_std for creation in completed.creations if creation.score_std is not None
    ]

    assert per_run_spreads
    assert any(spread > 0 for spread in per_run_spreads), (
        "every per-creation standard deviation is zero: the M runs are identical"
    )


# ------------------------------------------------------------------------------ reproducibility


def test_two_runs_with_the_same_config_and_seed_produce_identical_scores(config) -> None:
    """The acceptance criterion. Different run directories, byte-identical results."""
    first = execute_run(config, progress=False)
    second = execute_run(config, run_id="second", progress=False)

    assert first.run_dir != second.run_dir
    assert (first.run_dir / "scores.csv").read_text(encoding="utf-8") == (
        second.run_dir / "scores.csv"
    ).read_text(encoding="utf-8")


def test_the_second_run_costs_no_provider_calls(config) -> None:
    """Everything went through the cache, so a repeat is free."""
    first = execute_run(config, progress=False)
    second = execute_run(config, run_id="second", progress=False)

    assert first.manifest["calls"]["live"] > 0
    assert second.manifest["calls"]["live"] == 0
    assert second.manifest["calls"]["cached"] == first.manifest["calls"]["total"]


# ------------------------------------------------------------------------------- immutability


def test_a_completed_run_is_never_overwritten(config, completed) -> None:
    """R9. The classic failure this prevents is undetectable afterwards."""
    assert is_complete(completed.run_dir)

    with pytest.raises(RunError, match="already complete"):
        execute_run(config, run_id=completed.run_dir.name, progress=False)


def test_an_interrupted_run_may_be_resumed(config) -> None:
    """A directory without an end time is an interrupted run, not a result."""
    run_dir = config.path(config.run.out_dir) / "interrupted"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text('{"run_id": "interrupted"}', encoding="utf-8")

    assert not is_complete(run_dir)
    result = execute_run(config, run_id="interrupted", progress=False)

    assert is_complete(result.run_dir)


# ---------------------------------------------------------------------------------- the plan


def test_the_dry_run_plan_predicts_the_call_count(config) -> None:
    """A dry run is only useful if its number is the number.

    This is what makes it safe to approve a wide job from the plan alone.
    """
    plan = plan_run(config)
    result = execute_run(config, progress=False)

    assert plan.total_calls == result.manifest["calls"]["total"]
    assert plan.profile_calls == result.manifest["calls"]["by_tag"]["profile"]
    assert plan.rewrite_calls == result.manifest["calls"]["by_tag"]["rewrite"]


def test_the_plan_writes_nothing(config) -> None:
    """`--dry-run` must be safe to run against a production configuration."""
    plan_run(config)

    assert not config.path(config.run.out_dir).exists()


def test_the_plan_names_the_creations_it_would_inject(config) -> None:
    """So a reader can see what the robustness test will actually use."""
    plan = plan_run(config)

    assert len(plan.noise_creations) == config.run.M - 1
    assert plan.n_creations == 3


# ------------------------------------------------------------------------------- the manifest


def test_the_manifest_records_what_the_run_was(completed) -> None:
    """Enough to reproduce it, and enough to say what it cost."""
    manifest = completed.manifest

    assert manifest["run_id"] == completed.run_dir.name
    assert manifest["started_utc"] and manifest["ended_utc"]
    assert manifest["package_version"]
    assert manifest["provider"] == "fake"
    assert manifest["config_hash"]
    assert manifest["calls"]["total"] > 0
    assert manifest["counts"]["n_creations"] == 3
    assert manifest["threshold"]["method"] == "otsu_exact"


def test_the_manifest_accounts_for_every_call(completed) -> None:
    """The ledger and the manifest must agree, or one of them is wrong."""
    from mmlsa.llm.ledger import read_ledger

    entries = read_ledger(completed.run_dir / "calls.jsonl")

    assert completed.manifest["calls"]["total"] == len(entries)


def test_the_threshold_artifact_records_its_diagnostics(completed) -> None:
    """The report states the bimodality check rather than asserting it."""
    payload = json.loads((completed.run_dir / "threshold.json").read_text(encoding="utf-8"))

    assert "tau" in payload
    assert "separability" in payload["diagnostics"]
    assert "flags" in payload["diagnostics"]
