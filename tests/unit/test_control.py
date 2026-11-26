"""The control experiment's deterministic parts: the sample, the statistics and the Mode B request.

Expected values are worked by hand where the arithmetic is short, and checked against scipy's own
paired tests where it is not, so the two implementations would have to be wrong in the same way.
"""

from __future__ import annotations

import math

import pytest
from scipy import stats

from mmlsa import prompts
from mmlsa.chunking import Chunk
from mmlsa.experiments.control import (
    ControlError,
    achieved_power,
    allocate,
    paired_statistics,
    select_control_sample,
)
from mmlsa.pipeline.rewrite import GENERIC_TAG, build_generic_rewrite_request


def chunks_of(**counts: int) -> dict[str, list[Chunk]]:
    """Creations with the given numbers of one-word chunks."""
    return {
        name: [Chunk(name, index, f"word{index}", 1, index, index + 1) for index in range(count)]
        for name, count in counts.items()
    }


# ------------------------------------------------------------------------------------ allocation


def test_allocation_is_proportional_to_chunk_count() -> None:
    assert allocate({"a": 10, "b": 30, "c": 60}, 10) == {"a": 1, "b": 3, "c": 6}


def test_allocation_gives_the_leftover_to_the_largest_remainders() -> None:
    """Shares 2.25, 2.25 and 4.5: the one chunk left over goes to c, whose remainder is largest."""
    assert allocate({"a": 5, "b": 5, "c": 10}, 9) == {"a": 2, "b": 2, "c": 5}


def test_a_tie_on_remainder_is_broken_by_creation_id() -> None:
    """Three equal shares of two thirds each: the two chunks go to a and b, in id order."""
    assert allocate({"c": 1, "b": 1, "a": 1}, 2) == {"a": 1, "b": 1, "c": 0}


def test_allocation_takes_everything_when_the_sample_is_the_corpus() -> None:
    assert allocate({"a": 2, "b": 3}, 5) == {"a": 2, "b": 3}
    assert allocate({"a": 2, "b": 3}, 50) == {"a": 2, "b": 3}


@pytest.mark.parametrize("size", [1, 7, 13, 99, 250])
def test_allocation_sums_to_the_size_and_never_exceeds_a_creation(size: int) -> None:
    counts = {"a": 3, "b": 41, "c": 17, "d": 120, "e": 1}
    allocation = allocate(counts, size)

    assert sum(allocation.values()) == min(size, sum(counts.values()))
    assert all(allocation[name] <= counts[name] for name in counts)


# ---------------------------------------------------------------------------------------- sample


def test_the_sample_is_stratified_sorted_and_without_repeats() -> None:
    chunks = chunks_of(a=10, b=30, c=60)
    sample = select_control_sample(chunks, 10, seed=7)

    keys = [(chunk.creation_id, chunk.index) for chunk in sample]
    assert keys == sorted(keys)
    assert len(set(keys)) == 10
    assert [chunk.creation_id for chunk in sample].count("c") == 6


def test_the_sample_is_fixed_by_its_seed() -> None:
    """R8: the same seed draws the same chunks; another seed draws others."""
    chunks = chunks_of(a=40, b=40)

    first = select_control_sample(chunks, 10, seed=20260731)
    assert first == select_control_sample(chunks, 10, seed=20260731)
    assert first != select_control_sample(chunks, 10, seed=1)


def test_a_flat_sample_draws_from_every_chunk() -> None:
    sample = select_control_sample(chunks_of(a=5, b=5), 4, seed=3, stratify=False)

    assert len(sample) == 4
    assert len({(chunk.creation_id, chunk.index) for chunk in sample}) == 4


def test_an_empty_corpus_has_nothing_to_sample() -> None:
    with pytest.raises(ControlError, match="no chunks"):
        select_control_sample({"a": []}, 5, seed=0)


# ------------------------------------------------------------------------------------ statistics


def test_the_paired_statistics_match_the_worked_example() -> None:
    """Differences -1, -2, -3, -4: mean -2.5, variance 5/3, so t = -2.5 / sqrt(5/12)."""
    result = paired_statistics([1, 2, 3, 4], [2, 4, 6, 8])

    sd = math.sqrt(5 / 3)
    assert result.n == 4
    assert result.df == 3
    assert result.mean_difference == pytest.approx(-2.5)
    assert result.sd_difference == pytest.approx(sd)
    assert result.t_statistic == pytest.approx(-2.5 / (sd / 2))
    assert result.cohens_d == pytest.approx(-2.5 / sd)
    margin = stats.t.ppf(0.975, 3) * sd / 2
    assert result.ci_low == pytest.approx(-2.5 - margin)
    assert result.ci_high == pytest.approx(-2.5 + margin)


def test_the_p_values_agree_with_scipy() -> None:
    a = [0.031, 0.044, 0.027, 0.052, 0.038, 0.041, 0.029, 0.035, 0.047, 0.033]
    b = [0.042, 0.049, 0.031, 0.061, 0.037, 0.055, 0.036, 0.044, 0.050, 0.039]
    result = paired_statistics(a, b)

    t_test = stats.ttest_rel(a, b)
    assert result.t_statistic == pytest.approx(t_test.statistic)
    assert result.p_two_sided == pytest.approx(t_test.pvalue)
    assert result.p_less == pytest.approx(stats.ttest_rel(a, b, alternative="less").pvalue)
    assert result.wilcoxon_p_two_sided == pytest.approx(stats.wilcoxon(a, b).pvalue)
    assert result.wilcoxon_p_less == pytest.approx(stats.wilcoxon(a, b, alternative="less").pvalue)


def test_mode_a_significantly_lower_passes() -> None:
    result = paired_statistics([1, 2, 3, 4], [2, 4, 6, 8])

    assert result.verdict == "pass"
    assert result.p_two_sided < 0.05


def test_mode_a_significantly_higher_fails() -> None:
    """Significance in the wrong direction is the profile making things worse, not a pass."""
    result = paired_statistics([2, 4, 6, 8], [1, 2, 3, 4])

    assert result.verdict == "fail"
    assert "higher" in result.reason


def test_no_significant_difference_fails() -> None:
    result = paired_statistics([1.0, 2.0, 3.0, 4.0], [1.1, 1.9, 3.2, 3.9])

    assert result.verdict == "fail"
    assert "no significant difference" in result.reason


def test_the_alternative_decides_which_p_value_counts() -> None:
    """Two-sided p 0.110, one-sided 0.055: at alpha 0.06 only the one-sided reading passes (Q20)."""
    differences = [-0.5, -1.0, 0.2, -0.7, 0.1, -0.3]
    a, b = differences, [0.0] * len(differences)

    two_sided = paired_statistics(a, b, alpha=0.06, alternative="two-sided")
    one_sided = paired_statistics(a, b, alpha=0.06, alternative="less")

    assert two_sided.p_two_sided == pytest.approx(0.1103, abs=1e-4)
    assert one_sided.p_less == pytest.approx(two_sided.p_two_sided / 2)
    assert (two_sided.verdict, one_sided.verdict) == ("fail", "pass")


def test_too_few_pairs_is_undefined() -> None:
    result = paired_statistics([0.1], [0.2])

    assert result.verdict == "undefined"
    assert result.t_statistic is None
    assert result.mean_difference == pytest.approx(-0.1)


def test_identical_differences_are_undefined() -> None:
    """A standard deviation of zero leaves no t statistic; the test must not divide by it."""
    result = paired_statistics([1, 2, 3], [2, 3, 4])

    assert result.verdict == "undefined"
    assert result.sd_difference == 0


def test_unpaired_input_is_refused() -> None:
    with pytest.raises(ControlError, match="unpaired"):
        paired_statistics([0.1, 0.2], [0.1])


def test_power_at_no_effect_is_alpha() -> None:
    """With no effect the test rejects exactly as often as its size."""
    assert achieved_power(0.0, 30, 0.05, "two-sided") == pytest.approx(0.05)
    assert achieved_power(0.0, 30, 0.05, "less") == pytest.approx(0.05)


def test_power_grows_with_the_sample() -> None:
    small, large = (
        achieved_power(-0.3, 20, 0.05, "two-sided"),
        achieved_power(-0.3, 300, 0.05, "two-sided"),
    )

    assert small < large
    assert large > 0.99


def test_power_can_be_left_out() -> None:
    assert paired_statistics([1, 2, 3, 4], [2, 4, 6, 8], report_power=False).power is None


def test_the_statistics_serialize_to_json_values() -> None:
    payload = paired_statistics([0.1], [0.2]).to_dict()

    assert payload["verdict"] == "undefined"
    assert all(value is None or isinstance(value, (int, float, str)) for value in payload.values())


# ---------------------------------------------------------------------------------- the request


def test_the_mode_b_request_names_the_configured_author_and_no_profile() -> None:
    request = build_generic_rewrite_request("The passage itself.", "Test Author")

    assert request.prompt == prompts.render(
        prompts.REWRITE_GENERIC, author_label="Test Author", passage="The passage itself."
    )
    assert "Test Author's style" in request.prompt
    assert request.tag == GENERIC_TAG
    assert request.prompt_schema_version == prompts.template_version(prompts.REWRITE_GENERIC)


def test_a_mode_b_retry_appends_the_same_clarification_as_mode_a() -> None:
    first = build_generic_rewrite_request("Text.", "Test Author")
    retry = build_generic_rewrite_request("Text.", "Test Author", retry_round=1, replicate=2)

    assert retry.prompt == first.prompt + prompts.load_template(prompts.REWRITE_RETRY)
    assert (retry.retry_round, retry.replicate) == (1, 2)
