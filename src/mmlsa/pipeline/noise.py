"""Noise injection: one different foreign creation per run, from run 2 onward.

The main proposal in the approved book. Runs 2 to `M` each add **one** foreign creation to the
corpus before profile extraction, a fresh intruder each time. Run 1 is the plain corpus, and the
noise never accumulates: run `i` contains exactly one foreign creation, not `i - 1` of them.

The point is a robustness claim: a single foreign creation should not change how the authentic
creations are classified. Averaging the per-creation scores across runs is what makes the result
robust to it.

Three properties, all tested:

*Selection is deterministic.* The pool is sorted by identifier and consumed in order, offset by the
run seed. Two runs with the same seed inject the same texts in the same order, or the runs would
differ for a reason that has nothing to do with the method.

*The injected texts are distinct.* `M - 1` runs get `M - 1` different creations. Injecting the same
text twice would test less than it appears to.

*The noise never reaches the threshold.* It is scored, and reported separately as a diagnostic, but
it contributes nothing to `tau` and never appears in the suspicious set
(``docs/DECISIONS.md`` I7, ``docs/OPEN_QUESTIONS.md`` Q2).

See ``docs/SPEC.md`` section 3, Step 1.
"""

from __future__ import annotations

from dataclasses import dataclass


class NoiseError(Exception):
    """Raised when the noise pool cannot supply what the configuration asks of it."""


@dataclass(frozen=True)
class NoiseAssignment:
    """Which foreign creation, if any, each run receives."""

    by_run: dict[int, str]

    def for_run(self, run_index: int) -> str:
        """The creation injected into a given run, or an empty string for none."""
        return self.by_run.get(run_index, "")

    @property
    def injected(self) -> list[str]:
        """Every injected creation, in run order."""
        return [self.by_run[run] for run in sorted(self.by_run)]


def select_noise(
    pool_ids: list[str],
    n_runs: int,
    seed: int,
    *,
    enabled: bool = True,
    first_run_plain: bool = True,
) -> NoiseAssignment:
    """Assign one foreign creation to each run that takes one.

    The pool is **sorted by identifier** before anything else, so the assignment does not depend on
    filesystem order or on the order of a YAML file. The seed then chooses a starting offset, and the
    pool is consumed in order from there. This is the specified rule, and it makes the assignment a
    pure function of ``(pool, n_runs, seed)``.

    Raises when the pool is too small rather than reusing a text, because reusing one would quietly
    weaken the robustness claim the injection exists to test.
    """
    if not enabled:
        return NoiseAssignment(by_run={})

    first_noisy_run = 2 if first_run_plain else 1
    runs_needing_noise = list(range(first_noisy_run, n_runs + 1))

    if not runs_needing_noise:
        return NoiseAssignment(by_run={})

    ordered = sorted(pool_ids)
    if len(ordered) < len(runs_needing_noise):
        raise NoiseError(
            f"the noise pool holds {len(ordered)} creations but {len(runs_needing_noise)} runs need "
            "a different one each. Add texts to the pool, or lower run.M. Reusing a text would test "
            "less than it appears to."
        )

    offset = seed % len(ordered)
    return NoiseAssignment(
        by_run={
            run: ordered[(offset + position) % len(ordered)]
            for position, run in enumerate(runs_needing_noise)
        }
    )
