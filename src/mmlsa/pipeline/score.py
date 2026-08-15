"""Step 5 — per-creation aggregation.

Within run ``i``, the score of creation ``w`` is the mean of its chunk deltas::

    s_i(w) = (1 / |chunks(w)|) * sum over c in chunks(w) of delta(c, r_i(c))

Across the ``M`` runs, the final score is the mean of the per-run scores::

    score(w) = (1 / M) * sum over i = 1..M of s_i(w)

The sample standard deviation of the ``M`` per-run scores (``ddof = 1``) is the per-creation
confidence diagnostic the book asks for.

Two rules that decide what actually reaches the mean:

*Failed chunks are excluded*, and the divisor is the count of chunks that succeeded, not the count
attempted. The counts are carried through so that a score computed from few chunks is visibly that.

*A creation with no usable chunks has no score.* It is reported as unscorable rather than producing
a ``NaN`` that would silently propagate into the threshold and move it.

See ``docs/SPEC.md`` section 3, Step 5.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from enum import StrEnum


class ChunkStatus(StrEnum):
    """Outcome of rewriting and scoring one chunk."""

    OK = "ok"
    FAILED = "failed"
    """Rewriting did not produce an acceptable response within the retry budget."""


@dataclass(frozen=True)
class ChunkDelta:
    """One scored chunk within one run."""

    creation_id: str
    chunk_index: int
    delta: float
    n_words: int
    status: ChunkStatus = ChunkStatus.OK
    degenerate: bool = False


@dataclass(frozen=True)
class RunScore:
    """One creation's score within one run, with the accounting behind it."""

    creation_id: str
    run: int
    mean_delta: float | None
    n_chunks_total: int
    n_chunks_used: int
    n_chunks_failed: int
    n_chunks_degenerate: int
    length_weighted_mean: float | None

    @property
    def failed_fraction(self) -> float:
        """Share of this creation's chunks that failed in this run."""
        return self.n_chunks_failed / self.n_chunks_total if self.n_chunks_total else 0.0


@dataclass(frozen=True)
class CreationScore:
    """One creation's final score across all runs."""

    creation_id: str
    per_run: list[float | None]
    score: float | None
    score_std: float | None
    n_runs_scored: int
    unreliable: bool = False
    unreliable_reason: str = ""
    length_weighted_score: float | None = None
    diagnostics: dict[str, object] = field(default_factory=dict)

    @property
    def scorable(self) -> bool:
        """Whether this creation produced a usable score at all."""
        return self.score is not None


def aggregate_run(
    creation_id: str,
    run: int,
    deltas: list[ChunkDelta],
) -> RunScore:
    """Reduce one creation's chunk deltas within one run to a single score.

    The length-weighted mean is computed alongside the specified unweighted one, as the sensitivity
    check recorded in ``docs/OPEN_QUESTIONS.md`` Q3. The unweighted value remains the headline number.
    """
    used = [d for d in deltas if d.status is ChunkStatus.OK]
    failed = [d for d in deltas if d.status is ChunkStatus.FAILED]

    mean_delta = statistics.fmean(d.delta for d in used) if used else None

    total_words = sum(d.n_words for d in used)
    length_weighted = (
        sum(d.delta * d.n_words for d in used) / total_words if used and total_words else None
    )

    return RunScore(
        creation_id=creation_id,
        run=run,
        mean_delta=mean_delta,
        n_chunks_total=len(deltas),
        n_chunks_used=len(used),
        n_chunks_failed=len(failed),
        n_chunks_degenerate=sum(1 for d in used if d.degenerate),
        length_weighted_mean=length_weighted,
    )


def aggregate_creation(
    creation_id: str,
    run_scores: list[RunScore],
    *,
    std_ddof: int = 1,
    max_failed_fraction: float = 0.02,
) -> CreationScore:
    """Average a creation's per-run scores into its final score and confidence diagnostic.

    ``score_std`` needs at least two scored runs to exist; with one it is ``None`` rather than zero,
    because zero would claim a confidence the single run cannot support.
    """
    per_run = [rs.mean_delta for rs in run_scores]
    scored = [value for value in per_run if value is not None]

    if not scored:
        return CreationScore(
            creation_id=creation_id,
            per_run=per_run,
            score=None,
            score_std=None,
            n_runs_scored=0,
            unreliable=True,
            unreliable_reason="no chunk produced a usable delta in any run",
        )

    weighted = [rs.length_weighted_mean for rs in run_scores if rs.length_weighted_mean is not None]

    reasons: list[str] = []
    if len(scored) < len(run_scores):
        reasons.append(f"scored in only {len(scored)} of {len(run_scores)} runs")

    worst_failed = max((rs.failed_fraction for rs in run_scores), default=0.0)
    if worst_failed > max_failed_fraction:
        reasons.append(
            f"failed-chunk fraction {worst_failed:.3f} exceeds {max_failed_fraction:.3f}"
        )

    return CreationScore(
        creation_id=creation_id,
        per_run=per_run,
        score=statistics.fmean(scored),
        score_std=statistics.stdev(scored) if len(scored) > std_ddof else None,
        n_runs_scored=len(scored),
        unreliable=bool(reasons),
        unreliable_reason="; ".join(reasons),
        length_weighted_score=statistics.fmean(weighted) if weighted else None,
        diagnostics={
            "n_chunks_total": [rs.n_chunks_total for rs in run_scores],
            "n_chunks_used": [rs.n_chunks_used for rs in run_scores],
            "n_chunks_failed": [rs.n_chunks_failed for rs in run_scores],
            "n_chunks_degenerate": [rs.n_chunks_degenerate for rs in run_scores],
            "max_failed_fraction": worst_failed,
        },
    )


def scorable_scores(creations: list[CreationScore]) -> tuple[list[str], list[float]]:
    """The creation ids and scores that are eligible for thresholding, in a stable order.

    Unscorable creations are dropped here rather than earlier, so that they still appear in the
    report with an explicit reason instead of vanishing from the output entirely.
    """
    eligible = sorted(
        (c for c in creations if c.score is not None),
        key=lambda c: c.creation_id,
    )
    return [c.creation_id for c in eligible], [c.score for c in eligible]  # type: ignore[misc]
