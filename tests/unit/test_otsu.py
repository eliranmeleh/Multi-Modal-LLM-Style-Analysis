"""Step 6 — exact Otsu, the cross-check, and the bimodality diagnostics."""

from __future__ import annotations

import numpy as np
import pytest

from mmlsa.pipeline.classify import (
    AUTHENTIC,
    SUSPICIOUS,
    ThresholdError,
    _partition,
    classify,
    compute_threshold,
    gmm_2,
    otsu_exact,
    otsu_skimage,
)

LOW_CLUSTER = [0.040, 0.042, 0.045, 0.047, 0.050, 0.051, 0.053, 0.055]
HIGH_CLUSTER = [0.190, 0.195, 0.200, 0.205, 0.210]
TWO_CLUSTERS = LOW_CLUSTER + HIGH_CLUSTER


# ------------------------------------------------------------------------------------ exact Otsu


def test_exact_otsu_recovers_a_known_split() -> None:
    """On a clearly separated set, tau falls strictly inside the gap between the clusters."""
    result = otsu_exact(TWO_CLUSTERS)

    assert max(LOW_CLUSTER) < result.tau < min(HIGH_CLUSTER)
    assert result.method == "otsu_exact"
    assert result.diagnostics["split_index"] == len(LOW_CLUSTER)


def test_tau_is_the_midpoint_of_the_two_scores_that_straddle_the_split() -> None:
    """tau = (s_k* + s_{k*+1}) / 2, exactly as specified."""
    result = otsu_exact(TWO_CLUSTERS)
    expected = (max(LOW_CLUSTER) + min(HIGH_CLUSTER)) / 2

    assert result.tau == pytest.approx(expected)


def test_exactly_n_minus_one_candidate_splits_are_evaluated() -> None:
    """No binning, so the candidate set is the N-1 gaps between sorted scores."""
    result = otsu_exact(TWO_CLUSTERS)

    assert result.diagnostics["n_candidate_splits"] == len(TWO_CLUSTERS) - 1
    assert len(result.diagnostics["candidate_variances"]) == len(TWO_CLUSTERS) - 1


def test_result_is_independent_of_input_order() -> None:
    """The scores are sorted internally; the caller's order must not matter."""
    forward = otsu_exact(TWO_CLUSTERS)
    shuffled = otsu_exact(list(reversed(TWO_CLUSTERS)))

    assert forward.tau == pytest.approx(shuffled.tau)


def test_hand_computed_two_point_case() -> None:
    """The smallest possible case, worked by hand.

    scores = [0.2, 0.8], N = 2, one candidate split at k = 1:
      w0 = 1/2, w1 = 1/2, mu0 = 0.2, mu1 = 0.8
      sigma_b^2 = 0.5 * 0.5 * (0.2 - 0.8)^2 = 0.25 * 0.36 = 0.09
      tau = (0.2 + 0.8) / 2 = 0.5
    """
    result = otsu_exact([0.2, 0.8])

    assert result.tau == pytest.approx(0.5)
    assert result.between_class_variance == pytest.approx(0.09)


def test_hand_computed_four_point_case() -> None:
    """scores = [0, 0, 1, 1]. The best split is the middle one.

    k = 2:  w0 = w1 = 0.5, mu0 = 0, mu1 = 1  ->  sigma_b^2 = 0.25 * 1 = 0.25
    k = 1:  w0 = 0.25, w1 = 0.75, mu0 = 0, mu1 = 2/3  ->  0.1875 * 4/9 = 0.0833...
    k = 3:  symmetric with k = 1.
    So k* = 2 and tau = (0 + 1) / 2 = 0.5.
    """
    result = otsu_exact([0.0, 0.0, 1.0, 1.0])

    assert result.tau == pytest.approx(0.5)
    assert result.between_class_variance == pytest.approx(0.25)
    assert result.diagnostics["split_index"] == 2


@pytest.mark.parametrize("scores", [[], [0.5]])
def test_fewer_than_two_scores_raises(scores: list[float]) -> None:
    """A threshold on one point is meaningless and must fail rather than return something."""
    with pytest.raises(ThresholdError, match="at least 2"):
        otsu_exact(scores)


def test_identical_scores_produce_a_threshold_equal_to_that_value() -> None:
    """Degenerate but well defined: every score sits on tau, so everything is authentic."""
    result = otsu_exact([0.3, 0.3, 0.3, 0.3])

    assert result.tau == pytest.approx(0.3)
    assert result.between_class_variance == pytest.approx(0.0)


# ---------------------------------------------------------------------------------- cross-checks


def test_exact_and_skimage_agree_on_the_split_not_on_the_number() -> None:
    """The two implementations choose the same split but report tau at different points in the gap.

    The exact form returns the midpoint ``(s_k* + s_{k*+1}) / 2``. ``skimage`` returns the centre of
    the last histogram bin below the split, which converges to ``max(lower class)`` as the bin count
    grows. On this data that is 0.055 against 0.1225: the two differ by half the gap, and a *wider*
    gap makes them differ *more*.

    Pinned here because it is counter-intuitive and because a future reader will otherwise
    reasonably assume the raw difference is the thing to check. It is not; the partition is.
    See docs/OPEN_QUESTIONS.md Q11.
    """
    exact = otsu_exact(TWO_CLUSTERS)
    binned = otsu_skimage(TWO_CLUSTERS)

    assert exact.tau == pytest.approx((max(LOW_CLUSTER) + min(HIGH_CLUSTER)) / 2)
    assert binned.tau == pytest.approx(max(LOW_CLUSTER), abs=1e-3)
    assert abs(exact.tau - binned.tau) > 0.005

    # Both land in the same gap, which is the claim the two methods actually share.
    assert max(LOW_CLUSTER) - binned.tau < 0.005
    assert max(LOW_CLUSTER) <= exact.tau <= min(HIGH_CLUSTER)


def test_the_binned_threshold_would_flip_the_boundary_creation() -> None:
    """Concrete evidence for the decision to use the exact form (docs/DECISIONS.md I2).

    ``skimage`` returns the centre of the bin holding the largest lower-class score, which sits
    fractionally *below* that score. The score therefore lands above the threshold and the creation
    is labelled suspicious, purely because of where a histogram bin edge fell.
    """
    binned = otsu_skimage(TWO_CLUSTERS)
    exact = otsu_exact(TWO_CLUSTERS)

    assert _partition(TWO_CLUSTERS, binned.tau) != _partition(TWO_CLUSTERS, exact.tau)
    assert len(_partition(TWO_CLUSTERS, binned.tau)) == len(HIGH_CLUSTER) + 1
    assert len(_partition(TWO_CLUSTERS, exact.tau)) == len(HIGH_CLUSTER)


def test_compute_threshold_records_the_cross_check_and_does_not_flag_agreement() -> None:
    """Both values are recorded; agreement is judged on the gap, so clean data is unflagged."""
    result = compute_threshold(TWO_CLUSTERS, cross_check_skimage=True)

    assert "skimage_tau" in result.diagnostics
    assert result.diagnostics["skimage_same_gap"] is True
    assert result.diagnostics["skimage_outside_gap"] < 0.005
    assert not result.flagged


def test_a_skimage_threshold_outside_the_split_gap_is_flagged() -> None:
    """A negative tolerance forces the in-gap check to fail, proving the check is live."""
    result = compute_threshold(TWO_CLUSTERS, cross_check_skimage=True, agreement_tol=-1.0)

    assert result.flagged
    assert any("skimage" in flag for flag in result.diagnostics["flags"])


def test_the_partition_helper_is_what_agreement_is_judged_on() -> None:
    """Any two thresholds inside the same gap induce the same partition; one outside does not."""
    scores = [0.04, 0.05, 0.19, 0.20]

    assert _partition(scores, 0.055) == _partition(scores, 0.1225) == frozenset({2, 3})
    assert _partition(scores, 0.045) == frozenset({1, 2, 3})


def test_partition_uses_the_strict_inequality() -> None:
    """A score exactly on tau is not above it, matching the authentic-on-ties rule."""
    assert _partition([0.1, 0.2, 0.3], 0.2) == frozenset({2})


# ------------------------------------------------------------------------ bimodality diagnostics


def test_a_clean_two_cluster_set_is_reported_bimodal_and_unflagged() -> None:
    """The positive control for the diagnostic."""
    result = compute_threshold(TWO_CLUSTERS)

    assert result.diagnostics["bimodal"] is True
    assert result.diagnostics["separability"] > 0.5
    assert result.diagnostics["gap_ratio"] > 0.5
    assert result.diagnostics["flags"] == []


def test_a_unimodal_set_fires_the_diagnostic_and_flags_the_run() -> None:
    """The acceptance criterion for M4: Otsu still returns a tau, and the run says do not trust it."""
    rng = np.random.default_rng(20260731)
    unimodal = list(rng.normal(loc=0.10, scale=0.01, size=49))

    result = compute_threshold(unimodal)

    assert result.diagnostics["bimodal"] is False
    assert result.flagged
    assert any("gap" in flag or "separability" in flag for flag in result.diagnostics["flags"])


def test_a_uniform_spread_is_not_mistaken_for_two_clusters() -> None:
    """Evenly spaced scores have no gap anywhere; the split is arbitrary and must be flagged."""
    result = compute_threshold([i / 100 for i in range(49)])

    assert result.diagnostics["bimodal"] is False
    assert result.flagged


# -------------------------------------------------------------------------- alternative methods


def test_gaussian_mixture_splits_the_same_data_between_the_clusters() -> None:
    """The named fallback must be usable, and must agree on data where agreement is obvious."""
    result = gmm_2(TWO_CLUSTERS, seed=0)

    assert max(LOW_CLUSTER) < result.tau < min(HIGH_CLUSTER)
    assert result.diagnostics["converged"] is True


def test_manual_method_uses_the_configured_value() -> None:
    """An explicitly justified threshold, for the case the book allows as a last resort."""
    result = compute_threshold(TWO_CLUSTERS, method="manual", manual_tau=0.12)

    assert result.tau == pytest.approx(0.12)
    assert result.method == "manual"


def test_manual_method_without_a_value_raises() -> None:
    """Selecting the manual classifier without a threshold is a configuration error."""
    with pytest.raises(ThresholdError, match="manual_tau"):
        compute_threshold(TWO_CLUSTERS, method="manual")


def test_unknown_method_raises() -> None:
    """Fails at the point of selection, not later with an unbound name."""
    with pytest.raises(ThresholdError, match="unknown threshold method"):
        compute_threshold(TWO_CLUSTERS, method="not_a_method")


# ------------------------------------------------------------------------------- classification


def test_scores_above_tau_are_suspicious_and_the_rest_authentic() -> None:
    """The labelling rule, applied to a set with a known answer."""
    ids = [f"text_{i}" for i in range(len(TWO_CLUSTERS))]
    threshold = compute_threshold(TWO_CLUSTERS)
    result = classify(ids, TWO_CLUSTERS, threshold)

    assert len(result.suspicious) == len(HIGH_CLUSTER)
    assert len(result.authentic) == len(LOW_CLUSTER)
    assert all(result.labels[i] == SUSPICIOUS for i in ids[len(LOW_CLUSTER) :])


def test_a_score_exactly_on_tau_classifies_as_authentic() -> None:
    """``score > tau`` is strict, so ties fall to authentic."""
    threshold = compute_threshold([0.0, 1.0])
    result = classify(["exactly_on_tau"], [threshold.tau], threshold)

    assert result.labels["exactly_on_tau"] == AUTHENTIC
    assert result.suspicious == []


def test_creations_near_tau_are_reported_as_a_third_category() -> None:
    """The classifier stays binary; the report gains a borderline column."""
    threshold = compute_threshold(TWO_CLUSTERS)
    near = threshold.tau + 0.005
    far = threshold.tau + 0.100

    result = classify(["near", "far"], [near, far], threshold, borderline_band=0.01)

    assert result.borderline == ["near"]
    assert result.labels["near"] == SUSPICIOUS
    assert result.labels["far"] == SUSPICIOUS


def test_mismatched_ids_and_scores_raise() -> None:
    """A silent zip truncation here would mislabel creations."""
    threshold = compute_threshold(TWO_CLUSTERS)

    with pytest.raises(ThresholdError, match="must correspond"):
        classify(["a", "b"], [0.1], threshold)
