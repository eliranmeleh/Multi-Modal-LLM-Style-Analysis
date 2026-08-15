"""Noise injection: which foreign creation each run receives.

The specification is precise about this, and each clause is a separate test: run 1 is plain, runs 2
to `M` each take a different creation, selection is a deterministic function of the seed, and the
injected texts are never members of the corpus.
"""

from __future__ import annotations

import re

import pytest

from mmlsa.pipeline.noise import NoiseError, select_noise

POOL = [f"noise_{letter}" for letter in "abcdefghij"]


def test_run_one_is_plain() -> None:
    """The specification: run 1 uses the plain corpus."""
    assignment = select_noise(POOL, n_runs=3, seed=1)

    assert assignment.for_run(1) == ""


def test_runs_two_onward_each_receive_one_creation() -> None:
    """One intruder per run, not a growing set."""
    assignment = select_noise(POOL, n_runs=4, seed=1)

    assert set(assignment.by_run) == {2, 3, 4}
    assert all(assignment.for_run(run) for run in (2, 3, 4))


def test_exactly_m_minus_one_creations_are_injected() -> None:
    """The count the acceptance criterion names."""
    for n_runs in (2, 3, 5):
        assert len(select_noise(POOL, n_runs=n_runs, seed=7).injected) == n_runs - 1


def test_the_injected_creations_are_all_distinct() -> None:
    """Injecting the same text twice would test less than it appears to."""
    injected = select_noise(POOL, n_runs=6, seed=13).injected

    assert len(injected) == len(set(injected)) == 5


def test_noise_never_accumulates() -> None:
    """Run `i` holds exactly one foreign creation, not `i - 1` of them.

    Modelled here as the assignment being one identifier per run rather than a growing collection;
    the orchestrator adds precisely that one to the corpus it profiles.
    """
    assignment = select_noise(POOL, n_runs=5, seed=3)

    assert all(isinstance(assignment.for_run(run), str) for run in range(1, 6))
    assert len(assignment.injected) == 4


# ------------------------------------------------------------------------------ determinism


def test_selection_is_a_deterministic_function_of_its_inputs() -> None:
    """Two runs with the same seed inject the same texts in the same order."""
    first = select_noise(POOL, n_runs=4, seed=20260731)
    second = select_noise(POOL, n_runs=4, seed=20260731)

    assert first.by_run == second.by_run


def test_selection_does_not_depend_on_the_order_of_the_pool() -> None:
    """The pool is sorted first, so filesystem or YAML order cannot change a run."""
    forward = select_noise(POOL, n_runs=4, seed=5)
    shuffled = select_noise(list(reversed(POOL)), n_runs=4, seed=5)

    assert forward.by_run == shuffled.by_run


def test_a_different_seed_generally_selects_a_different_starting_point() -> None:
    """The seed is what makes two configurations of the same corpus explore different intruders."""
    assignments = {tuple(select_noise(POOL, n_runs=3, seed=s).injected) for s in range(10)}

    assert len(assignments) > 1


def test_the_pool_is_consumed_in_sorted_order_from_the_seed_offset() -> None:
    """The specified rule, pinned exactly.

    Ten texts, seed 12, so the offset is 12 % 10 = 2 and runs 2, 3 and 4 take entries 2, 3 and 4 of
    the sorted pool.
    """
    injected = select_noise(POOL, n_runs=4, seed=12).injected

    assert injected == ["noise_c", "noise_d", "noise_e"]


def test_the_pool_wraps_around() -> None:
    """A pool only just large enough must still supply distinct texts."""
    injected = select_noise(POOL, n_runs=11, seed=8).injected

    assert len(injected) == 10
    assert sorted(injected) == sorted(POOL)


# --------------------------------------------------------------------------------- failures


def test_a_pool_too_small_is_an_error_rather_than_a_reused_text() -> None:
    """Reusing a text would quietly weaken the robustness claim the injection exists to test."""
    with pytest.raises(NoiseError, match="noise pool holds"):
        select_noise(POOL[:2], n_runs=5, seed=1)


def test_the_error_says_how_to_fix_it() -> None:
    """Add texts or lower M; the message should not require reading the source."""
    with pytest.raises(NoiseError, match=re.escape("lower run.M")):
        select_noise(POOL[:1], n_runs=4, seed=1)


# ------------------------------------------------------------------------------ switched off


def test_disabling_noise_injects_nothing() -> None:
    """Phase B evaluates the no-added-noise variant as a comparison (docs/DECISIONS.md S3)."""
    assignment = select_noise(POOL, n_runs=5, seed=1, enabled=False)

    assert assignment.by_run == {}
    assert assignment.injected == []


def test_an_empty_pool_is_fine_when_noise_is_disabled() -> None:
    """The no-noise variant must not require a pool it will never read."""
    assert select_noise([], n_runs=3, seed=1, enabled=False).injected == []


def test_a_single_run_needs_no_noise() -> None:
    """`M = 1` is the control experiment's configuration; there is no run 2 to inject into."""
    assert select_noise(POOL, n_runs=1, seed=1).injected == []


def test_first_run_plain_can_be_switched_off() -> None:
    """A configuration key, so the variant can be measured rather than argued about."""
    assignment = select_noise(POOL, n_runs=3, seed=1, first_run_plain=False)

    assert assignment.for_run(1) != ""
    assert len(assignment.injected) == 3
