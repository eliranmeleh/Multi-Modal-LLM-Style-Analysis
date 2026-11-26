"""The plan counts the calls already answered in the cache, so a run's real cost is known first.

Issue #21. Before this, ``DryRunPlan.cached_calls`` was never filled and every call was reported as
new, which hid the one number that says whether a run is about to pay for answers already bought.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mmlsa.pipeline.orchestrator import execute_run, plan_run
from mmlsa.settings import build_config
from tests.conftest import CONFIGS_DIR


def mini(tmp_path: Path, *extra: str):
    """The mini configuration, writing its runs and cache under ``tmp_path``."""
    return build_config(
        CONFIGS_DIR / "mini.yaml",
        set_options=[
            f"run.out_dir={(tmp_path / 'runs').as_posix()}",
            f"llm.cache_dir={(tmp_path / 'cache').as_posix()}",
            *extra,
        ],
    )


def files_under(path: Path) -> set[Path]:
    """Every file below ``path``, to show that the plan writes nothing."""
    return set(path.rglob("*")) if path.exists() else set()


def test_before_any_run_every_call_is_new(tmp_path: Path) -> None:
    """An empty cache answers nothing."""
    plan = plan_run(mini(tmp_path))

    assert plan.cache_checked
    assert plan.cached_calls == 0
    assert plan.calls_to_issue == plan.total_calls


def test_after_a_run_every_call_of_its_plan_is_saved(tmp_path: Path) -> None:
    """The property that matters: repeating a finished run is planned at zero new calls."""
    config = mini(tmp_path)
    execute_run(config, progress=False)

    plan = plan_run(config)

    assert plan.cached_calls == plan.total_calls
    assert plan.calls_to_issue == 0


def test_the_plan_writes_nothing(tmp_path: Path) -> None:
    """No cache entry, no ledger, no run directory: consulting the cache is read-only."""
    config = mini(tmp_path)
    execute_run(config, progress=False)
    before = files_under(tmp_path)

    plan_run(config)

    assert files_under(tmp_path) == before


def test_a_new_chunk_length_keeps_the_profiles_and_renews_the_rewrites(tmp_path: Path) -> None:
    """Step 1 does not depend on ``P``, so its answers are still saved. A rewrite is saved only
    where a chunk comes out with exactly the same text, as a text shorter than both lengths does.
    """
    execute_run(mini(tmp_path), progress=False)

    plan = plan_run(mini(tmp_path, "chunking.P=90"))

    assert plan.profile_calls <= plan.cached_calls < plan.total_calls
    assert plan.calls_to_issue > plan.rewrite_calls // 2


def test_another_model_has_nothing_saved(tmp_path: Path) -> None:
    """The model is part of every key, so a different one starts from zero."""
    execute_run(mini(tmp_path), progress=False)

    plan = plan_run(mini(tmp_path, "llm.model_id=fake-2"))

    assert plan.cached_calls == 0


@pytest.mark.parametrize("mode", ["refresh"])
def test_a_refresh_run_is_planned_as_all_new(tmp_path: Path, mode: str) -> None:
    """``refresh`` re-asks every question whatever is stored, so nothing counts as saved."""
    execute_run(mini(tmp_path), progress=False)

    plan = plan_run(mini(tmp_path, f"llm.mode={mode}"))

    assert plan.cache_checked
    assert plan.cached_calls == 0
