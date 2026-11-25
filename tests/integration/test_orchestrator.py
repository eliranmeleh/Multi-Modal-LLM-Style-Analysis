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


def test_runs_on_identical_inputs_each_get_their_own_answers(tmp_path: Path) -> None:
    """Stage 2a: `M` runs with no noise are `M` samples, not one sample served `M` times.

    ``docs/DECISIONS.md`` I32. Before the replicate index was in the cache key, run 2 of this
    configuration was answered entirely from run 1's cache entries.
    """
    from mmlsa.llm.ledger import read_ledger

    config = build_config(
        CONFIGS_DIR / "mini.yaml",
        set_options=[
            f"run.out_dir={(tmp_path / 'runs').as_posix()}",
            f"llm.cache_dir={(tmp_path / 'cache').as_posix()}",
            "noise.enabled=false",
        ],
    )
    first = execute_run(config, progress=False)
    entries = read_ledger(first.run_dir / "calls.jsonl")

    for run_index in (1, 2):
        own = [e for e in entries if e["run_index"] == run_index]
        assert own, f"no calls recorded for run {run_index}"
        assert not any(e["cached"] for e in own), f"run {run_index} was served from the cache"
    keys = {
        run_index: {e["cache_key"] for e in entries if e["run_index"] == run_index}
        for run_index in (1, 2)
    }
    assert keys[1].isdisjoint(keys[2])

    second = execute_run(config, run_id="second", progress=False)
    assert second.manifest["calls"]["live"] == 0


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


def interrupted_run(config, run_id: str = "interrupted") -> Path:
    """A run directory as an interrupted run leaves it: its snapshot, and no end time."""
    import yaml

    run_dir = config.path(config.run.out_dir) / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "config.snapshot.yaml").write_text(
        yaml.safe_dump(config.to_dict(), sort_keys=True), encoding="utf-8", newline="\n"
    )
    (run_dir / "manifest.json").write_text(f'{{"run_id": "{run_id}"}}', encoding="utf-8")
    return run_dir


def rebuilt(tmp_path: Path, *extra: str):
    """The fixture's configuration with further ``--set`` options, as a resumed command would pass."""
    return build_config(
        CONFIGS_DIR / "mini.yaml",
        set_options=[
            f"run.out_dir={(tmp_path / 'runs').as_posix()}",
            f"llm.cache_dir={(tmp_path / 'cache').as_posix()}",
            *extra,
        ],
    )


def test_a_run_resumes_under_the_configuration_it_started_with(config) -> None:
    """The ordinary resume: same command, same configuration, the run completes."""
    interrupted_run(config)

    result = execute_run(config, run_id="interrupted", progress=False)

    assert is_complete(result.run_dir)


def test_a_resume_may_change_how_fast_requests_are_sent(config, tmp_path) -> None:
    """Pacing does not change any answer, so a resume on another tier is allowed."""
    interrupted_run(config)
    faster = rebuilt(tmp_path, "llm.requests_per_minute=7", "llm.concurrency=2")

    result = execute_run(faster, run_id="interrupted", progress=False)

    assert is_complete(result.run_dir)


def test_a_resume_may_change_the_tag_and_the_report(config, tmp_path) -> None:
    """The tag names a run and the report shapes its output; neither changes an answer."""
    interrupted_run(config)
    relabelled = rebuilt(tmp_path, "run.tag=renamed", "report.figures=false")

    result = execute_run(relabelled, run_id="interrupted", progress=False)

    assert is_complete(result.run_dir)


def test_a_key_the_snapshot_lacks_is_explained_as_a_code_change(config) -> None:
    """A run started on older code has no entry for a key added since; the message says why."""
    import yaml

    run_dir = interrupted_run(config)
    snapshot_file = run_dir / "config.snapshot.yaml"
    snapshot = yaml.safe_load(snapshot_file.read_text(encoding="utf-8"))
    del snapshot["chunking"]["min_chunk_words"]
    snapshot_file.write_text(yaml.safe_dump(snapshot, sort_keys=True), encoding="utf-8")

    with pytest.raises(RunError, match=r"chunking\.min_chunk_words.*code changed"):
        execute_run(config, run_id="interrupted", progress=False)


def test_a_resume_under_another_model_is_refused(config, tmp_path) -> None:
    """R7. Half a run from one model and half from another would be averaged without a trace."""
    run_dir = interrupted_run(config)
    snapshot_before = (run_dir / "config.snapshot.yaml").read_bytes()
    other_model = rebuilt(tmp_path, "llm.model_id=another-model")

    with pytest.raises(RunError, match=r"llm\.model_id"):
        execute_run(other_model, run_id="interrupted", progress=False)

    assert (run_dir / "config.snapshot.yaml").read_bytes() == snapshot_before
    assert not is_complete(run_dir)


def test_a_resume_under_another_method_parameter_is_refused(config, tmp_path) -> None:
    """A changed chunk length would mix passages of two sizes in one run."""
    interrupted_run(config)
    other_length = rebuilt(tmp_path, "chunking.P=60")

    with pytest.raises(RunError, match=r"chunking\.P"):
        execute_run(other_length, run_id="interrupted", progress=False)


# ------------------------------------------------------------------- resuming under other code

STARTED = {"git_commit": "a" * 40, "dirty": False}


def code_as(monkeypatch, commit: str, dirty: bool = False) -> None:
    """Make the code version the orchestrator reads look like this, without touching git."""
    from mmlsa.pipeline import orchestrator

    monkeypatch.setattr(
        orchestrator, "_code_version", lambda root: {"git_commit": commit, "dirty": dirty}
    )


def started_at(run_dir: Path, version: dict) -> None:
    """Record the code an interrupted run started from, as a run does before its first call."""
    (run_dir / "code_version.json").write_text(json.dumps(version), encoding="utf-8")


def test_a_run_records_its_code_before_the_first_call(completed) -> None:
    """#14. The commit at the start, not only at the end, so a resume can be checked against it."""
    recorded = json.loads((completed.run_dir / "code_version.json").read_text(encoding="utf-8"))

    assert set(recorded) >= {"git_commit", "dirty", "started_utc"}
    assert isinstance(recorded["dirty"], bool)


def test_a_resume_under_the_same_code_continues(config, monkeypatch) -> None:
    started_at(interrupted_run(config), STARTED)
    code_as(monkeypatch, STARTED["git_commit"])

    result = execute_run(config, run_id="interrupted", progress=False)

    assert is_complete(result.run_dir)


def test_a_resume_under_another_commit_is_refused(config, monkeypatch) -> None:
    """Half a run from one version of the code and half from another, with no key to show it."""
    run_dir = interrupted_run(config)
    started_at(run_dir, STARTED)
    code_as(monkeypatch, "b" * 40)

    with pytest.raises(RunError, match=r"aaaaaaaaaaaa.*bbbbbbbbbbbb.*--allow-code-change"):
        execute_run(config, run_id="interrupted", progress=False)

    assert not is_complete(run_dir)


def test_a_resume_from_uncommitted_changes_is_refused(config, monkeypatch) -> None:
    """The same commit with local edits is not the same code."""
    started_at(interrupted_run(config), STARTED)
    code_as(monkeypatch, STARTED["git_commit"], dirty=True)

    with pytest.raises(RunError, match="uncommitted"):
        execute_run(config, run_id="interrupted", progress=False)


def test_a_run_started_with_uncommitted_changes_cannot_be_resumed_unchecked(
    config, monkeypatch
) -> None:
    """Its starting code cannot be identified, so nothing can show the resume matches it."""
    started_at(interrupted_run(config), {**STARTED, "dirty": True})
    code_as(monkeypatch, STARTED["git_commit"])

    with pytest.raises(RunError, match="uncommitted"):
        execute_run(config, run_id="interrupted", progress=False)


def test_allow_code_change_resumes_and_records_the_code_it_resumed_under(
    config, monkeypatch
) -> None:
    run_dir = interrupted_run(config)
    started_at(run_dir, STARTED)
    code_as(monkeypatch, "b" * 40)

    result = execute_run(config, run_id="interrupted", progress=False, allow_code_change=True)

    assert is_complete(result.run_dir)
    recorded = json.loads((run_dir / "code_version.json").read_text(encoding="utf-8"))
    assert recorded["git_commit"] == STARTED["git_commit"]
    assert [entry["git_commit"] for entry in recorded["resumed_under"]] == ["b" * 40]


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
