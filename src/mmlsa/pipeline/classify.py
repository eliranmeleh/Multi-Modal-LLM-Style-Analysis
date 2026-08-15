"""Step 6 — threshold classification.

The ``N`` averaged scores are sorted and a parameter-free one-dimensional threshold ``tau``
separates authentic from suspicious::

    suspicious = { w in W : score(w) > tau }

The inequality is strict, so a creation sitting exactly on ``tau`` classifies as **authentic**.

Otsu's method is the classifier the method is illustrated with, one of several compared in Phase B
(``docs/DECISIONS.md`` S7). It is implemented in its **exact** form: with only 49 points, the bin
count of the usual histogram formulation is a hidden hyperparameter that can move the threshold, so
the ``N - 1`` candidate splits are enumerated directly instead (``docs/DECISIONS.md`` I2).
``skimage`` is run alongside as a cross-check and both values are recorded.

See ``docs/SPEC.md`` section 3, Step 6.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np


class ThresholdError(Exception):
    """Raised when a threshold cannot be computed from the given scores."""


@dataclass(frozen=True)
class ThresholdResult:
    """A computed threshold and everything needed to judge whether to trust it."""

    tau: float
    method: str
    between_class_variance: float | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def flagged(self) -> bool:
        """Whether any diagnostic asks for the threshold to be inspected by hand."""
        return bool(self.diagnostics.get("flags"))


@dataclass(frozen=True)
class Classification:
    """The labels produced by applying a threshold to a set of scores."""

    tau: float
    labels: dict[str, str]
    suspicious: list[str]
    authentic: list[str]
    borderline: list[str]
    threshold: ThresholdResult


AUTHENTIC = "authentic"
SUSPICIOUS = "suspicious"


# ---------------------------------------------------------------------------------- exact Otsu


def otsu_exact(scores: Sequence[float]) -> ThresholdResult:
    """Otsu's criterion evaluated on every split of the sorted scores, with no binning.

    Sort the scores ``s_1 <= ... <= s_N``. For each split ``k`` in ``1 .. N-1``::

        w0 = k / N,                 w1 = 1 - w0
        mu0 = mean(s_1 .. s_k),     mu1 = mean(s_{k+1} .. s_N)
        sigma_b^2(k) = w0 * w1 * (mu0 - mu1)^2

    Choose ``k*`` maximizing ``sigma_b^2`` and set ``tau = (s_{k*} + s_{k*+1}) / 2``.

    This is the same criterion as the binned form with no free parameter, and it converges to the
    binned result as the bin count grows.
    """
    ordered = sorted(float(s) for s in scores)
    n = len(ordered)
    if n < 2:
        raise ThresholdError(f"a threshold needs at least 2 scores, got {n}")

    values = np.asarray(ordered, dtype=float)
    total = values.sum()
    prefix = np.cumsum(values)

    best_k = 0
    best_variance = -1.0
    variances: list[float] = []

    for k in range(1, n):
        w0 = k / n
        w1 = 1.0 - w0
        mu0 = prefix[k - 1] / k
        mu1 = (total - prefix[k - 1]) / (n - k)
        variance = w0 * w1 * (mu0 - mu1) ** 2
        variances.append(float(variance))
        if variance > best_variance:
            best_variance = float(variance)
            best_k = k

    tau = (ordered[best_k - 1] + ordered[best_k]) / 2.0
    total_variance = float(np.var(values))

    return ThresholdResult(
        tau=tau,
        method="otsu_exact",
        between_class_variance=best_variance,
        diagnostics={
            "n_scores": n,
            "n_candidate_splits": n - 1,
            "split_index": best_k,
            "split_lower": ordered[best_k - 1],
            "split_upper": ordered[best_k],
            "gap": ordered[best_k] - ordered[best_k - 1],
            "total_variance": total_variance,
            "separability": (best_variance / total_variance) if total_variance > 0 else 0.0,
            "candidate_variances": variances,
        },
    )


def otsu_skimage(scores: Sequence[float]) -> ThresholdResult:
    """The binned ``skimage`` implementation, used only as a cross-check on the exact form."""
    from skimage.filters import threshold_otsu

    values = np.asarray([float(s) for s in scores], dtype=float)
    if values.size < 2:
        raise ThresholdError(f"a threshold needs at least 2 scores, got {values.size}")
    if np.allclose(values, values[0]):
        raise ThresholdError("all scores are identical; no threshold separates them")

    tau = float(threshold_otsu(values))
    return ThresholdResult(
        tau=tau, method="otsu_skimage", diagnostics={"n_scores": int(values.size)}
    )


def gmm_2(scores: Sequence[float], *, seed: int = 0) -> ThresholdResult:
    """A two-component Gaussian-mixture split, the named fallback when the data is not bimodal.

    The threshold is the point between the two component means where the posterior crosses 0.5,
    located on a fine grid. Reported alongside Otsu rather than silently substituted for it
    (``docs/OPEN_QUESTIONS.md`` Q9).
    """
    from sklearn.mixture import GaussianMixture

    values = np.asarray([float(s) for s in scores], dtype=float).reshape(-1, 1)
    if values.size < 2:
        raise ThresholdError(f"a threshold needs at least 2 scores, got {values.size}")

    model = GaussianMixture(n_components=2, random_state=seed, n_init=5).fit(values)
    means = sorted(float(m) for m in model.means_.ravel())

    grid = np.linspace(means[0], means[1], 4096).reshape(-1, 1)
    posterior = model.predict_proba(grid)
    lower_component = int(np.argmin(model.means_.ravel()))
    crossings = np.where(np.diff(np.sign(posterior[:, lower_component] - 0.5)) != 0)[0]

    tau = float(grid[crossings[0], 0]) if crossings.size else float(statistics.fmean(means))

    return ThresholdResult(
        tau=tau,
        method="gmm_2",
        diagnostics={
            "n_scores": int(values.size),
            "component_means": means,
            "component_weights": sorted(float(w) for w in model.weights_.ravel()),
            "converged": bool(model.converged_),
        },
    )


# ------------------------------------------------------------------------------------ selection


def _partition(scores: Sequence[float], tau: float) -> frozenset[int]:
    """The indices of the scores a threshold places above it.

    Two thresholds are equivalent for this method's purposes when they induce the same partition,
    whatever numeric value each reports.
    """
    return frozenset(index for index, score in enumerate(scores) if float(score) > tau)


def compute_threshold(
    scores: Sequence[float],
    *,
    method: str = "otsu_exact",
    cross_check_skimage: bool = True,
    agreement_tol: float = 0.005,
    min_separability: float = 0.5,
    min_gap_ratio: float = 0.5,
    manual_tau: float | None = None,
    seed: int = 0,
) -> ThresholdResult:
    """Compute ``tau`` by the configured method, with cross-checks and bimodality diagnostics.

    The diagnostics answer the question the book poses as a visual sanity check: does ``tau`` fall in
    a real gap, or is it a line drawn through the middle of one cloud? Two measures are recorded:

    ``separability`` is Otsu's own criterion, the ratio of between-class to total variance. It is
    high when the split explains most of the spread.

    ``gap_ratio`` is the width of the gap at the split, in units of the overall standard deviation.
    A wide gap is what "visible gap in the sorted scatter" means numerically.

    Failing either raises a flag. A flag is not an error: it means the histogram must be inspected
    and the fallback considered, and it must be said so in the report.
    """
    if method == "manual":
        if manual_tau is None:
            raise ThresholdError("classify.method is 'manual' but no manual_tau was provided")
        primary = ThresholdResult(tau=float(manual_tau), method="manual")
    elif method == "otsu_exact":
        primary = otsu_exact(scores)
    elif method == "otsu_skimage":
        primary = otsu_skimage(scores)
    elif method == "gmm_2":
        primary = gmm_2(scores, seed=seed)
    else:
        raise ThresholdError(f"unknown threshold method '{method}'")

    diagnostics: dict[str, Any] = dict(primary.diagnostics)
    flags: list[str] = []

    reference = otsu_exact(scores) if method != "otsu_exact" else primary
    separability = float(reference.diagnostics["separability"])
    spread = float(np.std(np.asarray([float(s) for s in scores], dtype=float)))
    gap_ratio = float(reference.diagnostics["gap"]) / spread if spread > 0 else 0.0

    diagnostics["separability"] = separability
    diagnostics["gap_ratio"] = gap_ratio
    diagnostics["bimodal"] = separability >= min_separability and gap_ratio >= min_gap_ratio

    if separability < min_separability:
        flags.append(
            f"low separability {separability:.3f} < {min_separability:.3f}: the split explains "
            "little of the spread, so the distribution may not be bimodal"
        )
    if gap_ratio < min_gap_ratio:
        flags.append(
            f"narrow gap at the split, {gap_ratio:.3f} standard deviations < {min_gap_ratio:.3f}: "
            "tau does not fall in a visible gap"
        )

    if cross_check_skimage and method in {"otsu_exact", "otsu_skimage"}:
        try:
            cross = otsu_skimage(scores)
        except ThresholdError as exc:
            diagnostics["skimage_error"] = str(exc)
        else:
            # The two implementations identify the same split but report tau at different points:
            # the exact form returns the midpoint of the gap, skimage returns the centre of the
            # last histogram bin below the split, which sits just under the largest score of the
            # lower class. Comparing the two numbers directly measures half the gap width, so a
            # cleaner separation would look like a worse disagreement; and comparing the induced
            # partitions differs by the boundary score alone, on every run, by construction.
            #
            # What both methods genuinely assert is *which gap* the corpus splits at. That is the
            # comparison made here, with the specified tolerance absorbing the bin-centre offset.
            # See docs/OPEN_QUESTIONS.md Q11.
            lower = float(reference.diagnostics["split_lower"])
            upper = float(reference.diagnostics["split_upper"])
            outside = max(lower - cross.tau, cross.tau - upper, 0.0)

            diagnostics["skimage_tau"] = cross.tau
            diagnostics["skimage_difference"] = abs(cross.tau - primary.tau)
            diagnostics["skimage_outside_gap"] = outside
            diagnostics["skimage_same_gap"] = outside <= agreement_tol
            diagnostics["skimage_same_partition"] = _partition(scores, primary.tau) == _partition(
                scores, cross.tau
            )

            if outside > agreement_tol:
                flags.append(
                    f"the skimage threshold {cross.tau:.4f} lies {outside:.4f} outside the split "
                    f"gap [{lower:.4f}, {upper:.4f}], above the tolerance {agreement_tol:.4f}: "
                    "the two methods are splitting the corpus in different places"
                )

    diagnostics["flags"] = flags
    return ThresholdResult(
        tau=primary.tau,
        method=primary.method,
        between_class_variance=primary.between_class_variance,
        diagnostics=diagnostics,
    )


def classify(
    creation_ids: Sequence[str],
    scores: Sequence[float],
    threshold: ThresholdResult,
    *,
    borderline_band: float = 0.01,
) -> Classification:
    """Label each creation against ``tau``.

    ``score > tau`` is suspicious; equality is authentic, matching the strict inequality in the
    specification. Creations within ``borderline_band`` of ``tau`` are additionally reported as a
    third category, while the classifier itself stays binary.
    """
    if len(creation_ids) != len(scores):
        raise ThresholdError(
            f"{len(creation_ids)} creation ids but {len(scores)} scores; they must correspond"
        )

    labels: dict[str, str] = {}
    suspicious: list[str] = []
    authentic: list[str] = []
    borderline: list[str] = []

    for creation_id, score in zip(creation_ids, scores, strict=True):
        label = SUSPICIOUS if score > threshold.tau else AUTHENTIC
        labels[creation_id] = label
        (suspicious if label == SUSPICIOUS else authentic).append(creation_id)
        if abs(score - threshold.tau) <= borderline_band:
            borderline.append(creation_id)

    return Classification(
        tau=threshold.tau,
        labels=labels,
        suspicious=suspicious,
        authentic=authentic,
        borderline=borderline,
        threshold=threshold,
    )
