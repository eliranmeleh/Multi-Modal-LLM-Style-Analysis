"""The M9 comparison harness, over the mini corpus with the offline provider.

The comparison is what M9 hands to the supervisors, so the properties tested here are the ones that
would make it wrong rather than merely ugly:

* **every candidate sees the same passages**, or the comparison compares corpora rather than models;
* **the sample is deterministic**, so a model measured next month is comparable to one measured now;
* **the sample spreads across creations**, because ten chunks from one creation say much less than
  ten chunks from ten;
* **a candidate that cannot be built does not take the others down with it**, which is the normal
  case while only one provider has a key;
* **every call reaches the ledger** (R2), because a comparison whose calls were not recorded is an
  anecdote.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from mmlsa.llm.ledger import read_ledger
from mmlsa.pipeline.compare import (
    Candidate,
    ComparisonError,
    compare_models,
    plan_comparison,
    select_sample,
)
from mmlsa.settings import build_config
from tests.conftest import CONFIGS_DIR


@pytest.fixture
def config(tmp_path: Path):
    """The mini configuration, writing its cache under ``tmp_path``."""
    return build_config(
        CONFIGS_DIR / "mini.yaml",
        provider="fake",
        set_options=[f"llm.cache_dir={(tmp_path / 'cache').as_posix()}"],
    )


# ------------------------------------------------------------------------------------- candidates


@pytest.mark.parametrize(
    ("specification", "provider", "model_id"),
    [
        ("gemini", "gemini", None),
        ("gemini:gemini-2.5-flash", "gemini", "gemini-2.5-flash"),
        ("  openai:gpt-4.1-mini  ", "openai", "gpt-4.1-mini"),
    ],
)
def test_a_candidate_is_parsed_from_its_specification(
    specification: str, provider: str, model_id: str | None
) -> None:
    """``provider`` or ``provider:model_id``; a bare provider means its default."""
    candidate = Candidate.parse(specification)

    assert (candidate.provider, candidate.model_id) == (provider, model_id)


def test_a_specification_with_a_colon_and_no_model_is_refused() -> None:
    """``gemini:`` is a slip, and silently reading it as the default would hide it."""
    with pytest.raises(ComparisonError, match="names a provider but no model"):
        Candidate.parse("gemini:")


def test_the_candidate_label_is_usable_as_a_directory_name() -> None:
    """Artifacts are written per candidate, and a model id contains characters paths dislike."""
    assert Candidate.parse("gemini:gemini-2.5-flash").slug == "gemini_gemini_2_5_flash"


# ---------------------------------------------------------------------------------- the sample


def test_the_sample_spreads_across_creations(config) -> None:
    """Ten chunks from one creation would say much less than ten from ten."""
    from mmlsa.pipeline.compare import _chunk, _load_texts

    chunks = _chunk(_load_texts(config), config)
    sample = select_sample(chunks, size=6, seed=config.run.seed)

    assert len(sample) == 6
    assert len({chunk.creation_id for chunk in sample}) == len(chunks)


def test_the_sample_is_deterministic(config) -> None:
    """A model measured next month has to be comparable to one measured today (R8)."""
    from mmlsa.pipeline.compare import _chunk, _load_texts

    chunks = _chunk(_load_texts(config), config)

    first = select_sample(chunks, size=5, seed=99)
    second = select_sample(chunks, size=5, seed=99)
    different_seed = select_sample(chunks, size=5, seed=100)

    assert [chunk.sha256 for chunk in first] == [chunk.sha256 for chunk in second]
    assert [chunk.sha256 for chunk in first] != [chunk.sha256 for chunk in different_seed]


def test_the_sample_never_repeats_a_chunk(config) -> None:
    """Measuring one passage twice would weight it double in every mean."""
    from mmlsa.pipeline.compare import _chunk, _load_texts

    chunks = _chunk(_load_texts(config), config)
    sample = select_sample(chunks, size=9, seed=3)

    assert len({chunk.sha256 for chunk in sample}) == len(sample)


def test_a_corpus_with_no_chunks_is_an_error_rather_than_an_empty_comparison() -> None:
    """An empty comparison would report a table of zeros and look like a result."""
    with pytest.raises(ComparisonError, match="no chunks"):
        select_sample({}, size=5, seed=1)


# ------------------------------------------------------------------------------------- the plan


def test_the_plan_counts_a_profile_call_and_the_sample_for_every_candidate(config) -> None:
    """Run before spending. Profile extraction is the expensive half and is easy to forget."""
    candidates = [Candidate("fake", "fake-a"), Candidate("fake", "fake-b")]

    plan = plan_comparison(config, candidates, size=4)

    assert plan.n_chunks == 4
    assert len(plan.candidates) == 2
    assert plan.total_calls == sum(profile + 4 for _, _, profile in plan.candidates)
    assert plan.estimated_input_tokens > 0


def test_the_plan_names_the_model_each_candidate_would_resolve_to(config) -> None:
    """A bare provider name hides the most expensive decision in the command."""
    plan = plan_comparison(config, [Candidate("fake")], size=2)

    assert plan.candidates[0][1] == "fake-1"


# -------------------------------------------------------------------------------- the comparison


def test_every_candidate_rewrites_the_same_passages(config, tmp_path: Path) -> None:
    """The whole point: a difference between candidates must be a difference between models."""
    result = compare_models(
        config,
        [Candidate("fake", "fake-a"), Candidate("fake", "fake-b")],
        tmp_path / "compare",
        size=5,
    )

    assert len(result.models) == 2
    seen = [
        [(chunk.creation_id, chunk.chunk_index) for chunk in model.chunks]
        for model in result.models
    ]
    assert seen[0] == seen[1]
    assert len(seen[0]) == 5


def test_the_comparison_measures_what_the_acceptance_criterion_names(
    config, tmp_path: Path
) -> None:
    """Rewrite fidelity, output cleanliness and latency, per `docs/PLAN.md` M9."""
    result = compare_models(config, [Candidate("fake")], tmp_path / "compare", size=3)
    summary = result.table()[0]

    assert summary["n_ok"] > 0
    assert 0.0 < summary["mean_delta"] <= 1.0, "a fake that changed nothing would measure nothing"
    assert summary["mean_length_ratio"] > 0
    assert summary["mean_content_retention"] > 0
    assert summary["needed_cleaning"] == 0, "the offline provider emits no preamble"
    assert summary["median_latency_ms"] >= 0
    assert summary["input_tokens"] > 0


def test_a_candidate_that_cannot_be_built_does_not_stop_the_others(config, tmp_path: Path) -> None:
    """The normal case while only one provider has a key.

    A live candidate with no key raises at construction. That must be recorded against the candidate
    and reported, not raised out of the comparison, or the models that do work are never measured.
    """
    result = compare_models(
        config,
        [Candidate("fake"), Candidate("gemini", "gemini-2.5-flash")],
        tmp_path / "compare",
        size=2,
    )

    working, broken = result.models
    assert working.chunks and not working.error
    assert broken.error and not broken.chunks
    assert "GEMINI_API_KEY" in broken.error or "pip install" in broken.error


def test_the_comparison_writes_what_a_reader_needs(config, tmp_path: Path) -> None:
    """`summary.md` is the deliverable; `rewrites/` is what section 7 asks a human to read."""
    directory = tmp_path / "compare"
    compare_models(config, [Candidate("fake")], directory, size=3)

    assert (directory / "summary.md").is_file()
    assert (directory / "comparison.csv").is_file()
    assert (directory / "summary.json").is_file()
    assert (directory / "profiles" / "fake.json").is_file()

    side_by_side = sorted((directory / "rewrites").glob("*.md"))
    assert len(side_by_side) == 3

    first = side_by_side[0].read_text(encoding="utf-8")
    assert "## original" in first
    assert "## fake" in first

    rows = list(csv.DictReader((directory / "comparison.csv").open(encoding="utf-8")))
    assert len(rows) == 3
    assert {"model", "delta", "length_ratio", "content_retention", "latency_ms"} <= set(rows[0])


def test_the_summary_reports_a_candidate_that_could_not_be_measured(config, tmp_path: Path) -> None:
    """A missing model must be visible in the written artifact, not only in the logs."""
    directory = tmp_path / "compare"
    compare_models(config, [Candidate("fake"), Candidate("openai")], directory, size=2)

    summary = (directory / "summary.md").read_text(encoding="utf-8")
    assert "could not be measured" in summary
    assert "openai" in summary

    payload = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    assert payload["n_chunks"] == 2
    assert [model["model"] for model in payload["models"]] == ["fake", "openai"]


def test_every_call_reaches_the_ledger(config, tmp_path: Path) -> None:
    """R2. A comparison whose calls were not recorded is an anecdote, not evidence."""
    directory = tmp_path / "compare"
    compare_models(config, [Candidate("fake")], directory, size=3)

    entries = read_ledger(directory / "calls.jsonl")
    tags = [entry["tag"] for entry in entries]

    assert tags.count("rewrite") == 3
    assert tags.count("profile") >= 1
    assert all(entry["model_id"] for entry in entries)


def test_a_second_comparison_with_the_same_inputs_costs_nothing(config, tmp_path: Path) -> None:
    """Every call goes through the cache (R3), so re-reading a comparison is free."""
    first = compare_models(config, [Candidate("fake")], tmp_path / "one", size=3)
    second = compare_models(config, [Candidate("fake")], tmp_path / "two", size=3)

    assert first.table()[0]["mean_delta"] == second.table()[0]["mean_delta"]
    assert all(entry["cached"] for entry in read_ledger(tmp_path / "two" / "calls.jsonl"))


def test_comparing_nothing_is_an_error(config, tmp_path: Path) -> None:
    """An empty candidate list would write an empty table and look like a finished comparison."""
    with pytest.raises(ComparisonError, match="no candidate models"):
        compare_models(config, [], tmp_path / "compare")
