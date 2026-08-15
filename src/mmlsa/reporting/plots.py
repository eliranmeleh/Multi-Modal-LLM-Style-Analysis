"""Figures.

The sorted scatter is not decoration. The book makes it a validation step: `tau` must fall in a
visible gap, and agreement between the automatic threshold and that visible gap is the evidence that
the two-cluster structure is real. The figure is how a reader checks the claim without rerunning
anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display in CI or on a headless run

import matplotlib.pyplot as plt
import numpy as np

from mmlsa.pipeline.classify import ThresholdResult

AUTHENTIC_COLOUR = "#3B6FB6"
SUSPICIOUS_COLOUR = "#C1553B"
THRESHOLD_COLOUR = "#444444"


def sorted_scatter(
    creation_ids: Sequence[str],
    scores: Sequence[float],
    threshold: ThresholdResult,
    path: Path,
    *,
    title: str = "Per-creation style distance",
    annotate_top: int = 10,
) -> Path:
    """Scores sorted ascending with `tau` marked, the figure the book's sanity check refers to."""
    order = np.argsort(np.asarray(scores, dtype=float))
    ordered_scores = np.asarray(scores, dtype=float)[order]
    ordered_ids = [creation_ids[i] for i in order]
    positions = np.arange(len(ordered_scores))
    above = ordered_scores > threshold.tau

    figure, axes = plt.subplots(figsize=(10, 6))
    axes.scatter(
        positions[~above], ordered_scores[~above], color=AUTHENTIC_COLOUR, s=45, label="authentic"
    )
    axes.scatter(
        positions[above], ordered_scores[above], color=SUSPICIOUS_COLOUR, s=45, label="suspicious"
    )
    axes.axhline(
        threshold.tau,
        color=THRESHOLD_COLOUR,
        linestyle="--",
        linewidth=1.2,
        label=f"tau = {threshold.tau:.4f} ({threshold.method})",
    )

    for position, score, creation_id in list(
        zip(positions, ordered_scores, ordered_ids, strict=True)
    )[-annotate_top:]:
        axes.annotate(
            creation_id,
            (position, score),
            textcoords="offset points",
            xytext=(-6, 4),
            ha="right",
            fontsize=7,
            color="#333333",
        )

    axes.set_xlabel("creations, sorted by score")
    axes.set_ylabel("mean function-word edit distance")
    axes.set_title(title)
    axes.legend(loc="upper left", frameon=False)
    axes.spines[["top", "right"]].set_visible(False)

    if threshold.flagged:
        axes.text(
            0.99,
            0.02,
            "threshold flagged: see threshold.json",
            transform=axes.transAxes,
            ha="right",
            fontsize=8,
            color=SUSPICIOUS_COLOUR,
        )

    return _save(figure, path)


def histogram(
    scores: Sequence[float],
    threshold: ThresholdResult,
    path: Path,
    *,
    bins: int = 20,
    title: str = "Distribution of per-creation scores",
) -> Path:
    """The histogram the book asks to inspect when the distribution may not be bimodal."""
    figure, axes = plt.subplots(figsize=(8, 5))
    axes.hist(np.asarray(scores, dtype=float), bins=bins, color=AUTHENTIC_COLOUR, alpha=0.85)
    axes.axvline(
        threshold.tau,
        color=THRESHOLD_COLOUR,
        linestyle="--",
        linewidth=1.2,
        label=f"tau = {threshold.tau:.4f}",
    )

    separability = threshold.diagnostics.get("separability")
    gap_ratio = threshold.diagnostics.get("gap_ratio")
    if separability is not None and gap_ratio is not None:
        axes.set_title(f"{title}\nseparability {separability:.2f}, gap {gap_ratio:.2f} sd")
    else:
        axes.set_title(title)

    axes.set_xlabel("mean function-word edit distance")
    axes.set_ylabel("creations")
    axes.legend(frameon=False)
    axes.spines[["top", "right"]].set_visible(False)

    return _save(figure, path)


def run_variance(
    creation_ids: Sequence[str],
    per_run_scores: Sequence[Sequence[float | None]],
    path: Path,
    *,
    title: str = "Per-creation score across independent runs",
) -> Path:
    """Score spread across the `M` runs: the visual form of the reproducibility criterion."""
    figure, axes = plt.subplots(figsize=(10, 6))

    for position, (_creation_id, values) in enumerate(
        zip(creation_ids, per_run_scores, strict=True)
    ):
        present = [v for v in values if v is not None]
        if not present:
            continue
        axes.plot([position] * len(present), present, "o", color=AUTHENTIC_COLOUR, alpha=0.6, ms=4)
        axes.plot(
            [position, position], [min(present), max(present)], "-", color=AUTHENTIC_COLOUR, lw=1
        )

    axes.set_xticks(range(len(creation_ids)))
    axes.set_xticklabels(creation_ids, rotation=90, fontsize=6)
    axes.set_ylabel("mean function-word edit distance")
    axes.set_title(title)
    axes.spines[["top", "right"]].set_visible(False)

    return _save(figure, path)


def _save(figure: plt.Figure, path: Path) -> Path:
    """Write a figure and release it, so a long run does not accumulate open figures."""
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path
