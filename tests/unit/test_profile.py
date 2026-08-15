"""Step 1 — packing, extraction, merging and parsing.

The packing tests are the important half. If two runs divided the corpus differently, their profiles
would differ for reasons that have nothing to do with the model, and the run-to-run averaging in
Step 5 would be cancelling the wrong thing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger
from mmlsa.llm.providers.fake import FakeProvider
from mmlsa.llm.runner import Runner
from mmlsa.pipeline.profile import (
    ProfileError,
    StyleProfile,
    build_extraction_request,
    extract_profile,
    parse_profile,
    plan_packing,
)
from mmlsa.utils.tokens import PackingError, estimate_tokens, pack_creations
from tests.conftest import REPO_ROOT

MINI_CORPUS_DIR = REPO_ROOT / "tests" / "fixtures" / "mini_corpus"


@pytest.fixture(scope="module")
def mini_corpus() -> dict[str, str]:
    """The three development texts."""
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(MINI_CORPUS_DIR.glob("*.txt"))}


def make_runner(tmp_path: Path, context_window: int = 1_000_000) -> Runner:
    """A runner over ``FakeProvider``."""

    class Sized(FakeProvider):
        def context_window(self) -> int:
            return context_window

    return Runner(
        provider=Sized(),
        cache=ResponseCache(tmp_path / "cache"),
        ledger=Ledger(tmp_path / "runs" / "r1" / "calls.jsonl", run_id="r1"),
        concurrency=2,
    )


# --------------------------------------------------------------------------------------- packing


def test_no_creation_is_ever_split_across_calls() -> None:
    """The specification forbids truncation and sampling: a call holds complete creations."""
    sizes = {f"text_{i:02d}": 1000 + i * 37 for i in range(20)}
    bins = pack_creations(sizes, budget=5000)

    packed = [name for b in bins for name in b.creation_ids]
    assert sorted(packed) == sorted(sizes)
    assert len(packed) == len(set(packed))


def test_no_call_exceeds_the_budget() -> None:
    """The reason for packing at all."""
    sizes = {f"text_{i:02d}": 1000 + i * 37 for i in range(20)}
    bins = pack_creations(sizes, budget=5000)

    assert all(b.tokens <= 5000 for b in bins)


def test_packing_is_identical_across_invocations() -> None:
    """The acceptance criterion. Fully determined by the inputs, so any machine agrees."""
    sizes = {f"text_{i:02d}": 1000 + (i * 7919) % 900 for i in range(30)}

    first = pack_creations(sizes, budget=4000)
    second = pack_creations(dict(reversed(list(sizes.items()))), budget=4000)

    assert [b.creation_ids for b in first] == [b.creation_ids for b in second]


def test_packing_is_first_fit_decreasing_with_ties_broken_by_identifier() -> None:
    """The order the specification names, checked on a case where the two rules both bite.

    Four creations of 600, 600, 400 and 400 tokens into calls of 1000. Decreasing order with ties
    by identifier is b_large, d_large, a_small, c_small. First fit puts b_large in call 1, d_large
    does not fit so opens call 2, a_small joins call 1 (600 + 400 = 1000), c_small joins call 2.
    """
    sizes = {"b_large": 600, "d_large": 600, "a_small": 400, "c_small": 400}
    bins = pack_creations(sizes, budget=1000)

    assert len(bins) == 2
    assert bins[0].creation_ids == ("a_small", "b_large")
    assert bins[1].creation_ids == ("c_small", "d_large")


def test_a_corpus_that_fits_needs_one_call() -> None:
    """The small-corpus path, which is what the mini config exercises."""
    bins = pack_creations({"a": 100, "b": 200, "c": 300}, budget=10_000)

    assert len(bins) == 1
    assert bins[0].creation_ids == ("a", "b", "c")


def test_a_creation_too_large_for_any_call_is_an_error() -> None:
    """Truncating it is forbidden, so the only honest response is to refuse and say why."""
    with pytest.raises(PackingError, match="do not fit a single call"):
        pack_creations({"small": 100, "enormous": 999_999}, budget=1000)


def test_the_error_names_the_creations_that_do_not_fit() -> None:
    """With 49 texts, an unattributed failure costs an afternoon."""
    with pytest.raises(PackingError, match="enormous"):
        pack_creations({"enormous": 999_999}, budget=1000)


@pytest.mark.parametrize("budget", [0, -1])
def test_a_non_positive_budget_is_rejected(budget: int) -> None:
    """A misconfigured budget would otherwise loop or produce one call per creation."""
    with pytest.raises(PackingError, match="must be positive"):
        pack_creations({"a": 10}, budget=budget)


def test_prompt_overhead_reduces_the_usable_budget() -> None:
    """The template itself occupies part of every call."""
    without = pack_creations({"a": 900, "b": 900}, budget=2000)
    with_overhead = pack_creations({"a": 900, "b": 900}, budget=2000, prompt_overhead_tokens=500)

    assert len(without) == 1
    assert len(with_overhead) == 2


def test_token_estimation_is_conservative() -> None:
    """Under-estimating would overfill a call and truncate a creation, which is forbidden."""
    text = " ".join(["word"] * 1000)

    assert estimate_tokens(text) == 1350


def test_the_real_corpus_needs_more_than_one_call() -> None:
    """docs/DECISIONS.md I3: the multi-call path is the normal path, not a rare fallback.

    Pinned because the whole merge-call design exists on this premise. If a future model window made
    the corpus fit in one call, this test failing is the signal to revisit that design.
    """
    corpus_dir = REPO_ROOT / "data" / "corpus"
    if not corpus_dir.is_dir():
        pytest.skip("corpus not fetched")

    texts = {p.stem: p.read_text(encoding="utf-8") for p in corpus_dir.glob("*.txt")}
    bins = plan_packing(texts, context_window=1_000_000)

    assert len(bins) > 1
    assert sum(len(b.creation_ids) for b in bins) == 49


# --------------------------------------------------------------------------------------- parsing


def test_a_structured_response_parses_into_the_six_keys() -> None:
    """The documented representation."""
    response = (
        '{"vocabulary": "plain", "pronouns": "second person", "verb_forms": "older endings", '
        '"sentence_structure": "long clauses", "punctuation": "commas", "other": "metre"}'
    )
    profile = parse_profile(response)

    assert profile.structured
    assert len(profile.fields) == 6
    assert profile.fields["vocabulary"] == "plain"


def test_a_fenced_response_parses() -> None:
    """Models add Markdown fencing around JSON despite being asked not to."""
    response = '```json\n{"vocabulary": "plain", "pronouns": "second person"}\n```'
    profile = parse_profile(response)

    assert profile.structured
    assert profile.fields["vocabulary"] == "plain"


def test_a_response_with_surrounding_prose_still_parses() -> None:
    """The JSON object is extracted from a chatty response rather than the run being lost."""
    response = (
        'Here is the analysis:\n{"vocabulary": "plain", "pronouns": "second"}\nHope that helps.'
    )
    profile = parse_profile(response)

    assert profile.structured
    assert profile.fields["vocabulary"] == "plain"


def test_an_unparseable_response_falls_back_to_free_text() -> None:
    """The book's literal form is free text, so a formatting slip is not worth losing a run over."""
    profile = parse_profile("The style is plain, direct and heavily coordinated.")

    assert not profile.structured
    assert "plain, direct" in profile.free_text
    assert not profile.is_empty


def test_free_text_mode_does_not_attempt_to_parse() -> None:
    """``profile.structured_output: false`` restores the book's literal form."""
    profile = parse_profile('{"vocabulary": "plain"}', structured=False)

    assert not profile.structured
    assert profile.free_text.startswith("{")


def test_a_partial_structured_response_keeps_what_it_has() -> None:
    """Three of six keys is still a usable profile."""
    profile = parse_profile('{"vocabulary": "plain", "pronouns": "second", "other": "metre"}')

    assert profile.structured
    assert set(profile.fields) == {"vocabulary", "pronouns", "other"}


def test_an_empty_profile_is_recognisable_as_empty() -> None:
    """Rewriting every chunk against nothing would measure nothing, so this must be detectable."""
    assert StyleProfile(fields={}, structured=True).is_empty
    assert StyleProfile(free_text="   ", structured=False).is_empty


# ------------------------------------------------------------------------- end to end, offline


def test_the_mini_corpus_produces_a_profile_with_the_six_keys(
    mini_corpus: dict[str, str], tmp_path: Path
) -> None:
    """The M6 acceptance criterion, against FakeProvider and no network."""
    result = extract_profile(mini_corpus, make_runner(tmp_path), run_index=1)

    assert result.profile.structured
    assert set(result.profile.fields) == {
        "vocabulary",
        "pronouns",
        "verb_forms",
        "sentence_structure",
        "punctuation",
        "other",
    }
    assert result.packing["n_calls"] == 1
    assert result.merged is False


def test_a_corpus_that_needs_several_calls_is_merged(
    mini_corpus: dict[str, str], tmp_path: Path
) -> None:
    """Forcing a small window exercises the path the real corpus always takes."""
    result = extract_profile(mini_corpus, make_runner(tmp_path), run_index=1, budget_tokens=600)

    assert result.packing["n_calls"] > 1
    assert len(result.partials) == result.packing["n_calls"]
    assert result.merged is True
    assert set(result.profile.fields) == {
        "vocabulary",
        "pronouns",
        "verb_forms",
        "sentence_structure",
        "punctuation",
        "other",
    }


def test_extraction_is_identical_across_two_invocations(
    mini_corpus: dict[str, str], tmp_path: Path
) -> None:
    """Same corpus, same budget, same packing and same profile."""
    first = extract_profile(mini_corpus, make_runner(tmp_path / "a"), run_index=1)
    second = extract_profile(mini_corpus, make_runner(tmp_path / "b"), run_index=1)

    assert first.packing == second.packing
    assert first.profile.fields == second.profile.fields


def test_every_creation_reaches_exactly_one_call(
    mini_corpus: dict[str, str], tmp_path: Path
) -> None:
    """Full coverage at the corpus level, mirroring full coverage at the chunk level."""
    result = extract_profile(mini_corpus, make_runner(tmp_path), run_index=1, budget_tokens=600)

    packed = [name for b in result.packing["bins"] for name in b["creation_ids"]]
    assert sorted(packed) == sorted(mini_corpus)
    assert len(packed) == len(set(packed))


def test_the_second_invocation_costs_no_calls(mini_corpus: dict[str, str], tmp_path: Path) -> None:
    """Step 1 goes through the cache like everything else."""
    runner = make_runner(tmp_path)
    extract_profile(mini_corpus, runner, run_index=1)
    before = runner.stats.live

    extract_profile(mini_corpus, runner, run_index=1)

    assert runner.stats.live == before


def test_an_empty_corpus_is_refused(tmp_path: Path) -> None:
    """A profile of nothing would silently make every delta meaningless."""
    with pytest.raises(ProfileError, match="empty corpus"):
        extract_profile({}, make_runner(tmp_path))


def test_the_result_records_its_provenance(mini_corpus: dict[str, str], tmp_path: Path) -> None:
    """docs/SPEC.md Step 1 requires k, the packing and every partial profile in the artifacts."""
    result = extract_profile(mini_corpus, make_runner(tmp_path), run_index=2, budget_tokens=600)
    payload = result.to_dict()

    assert payload["run_index"] == 2
    assert payload["packing"]["n_calls"] >= 1
    assert len(payload["partials"]) == payload["packing"]["n_calls"]
    assert payload["profile"]["fields"]


def test_the_extraction_request_is_tagged_and_versioned() -> None:
    """The tag drives the ledger; the version drives cache invalidation."""
    request = build_extraction_request([("a", "some text")])

    assert request.tag == "profile"
    assert request.response_format == "json"
    assert request.prompt_schema_version >= 1
