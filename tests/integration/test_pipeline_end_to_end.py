"""All six steps, wired together, offline.

The orchestrator that does this for real arrives at M8. This test does it by hand over the mini
corpus, which is what makes it valuable now: it proves the seams between the steps fit before the
code that relies on them is written, and it is the first place a mismatch between Step 3's output
and Step 5's input would show up.

Nothing here touches a network. `FakeProvider` supplies deterministic rewrites, so the numbers are
reproducible but not meaningful; what is being checked is that the pipeline runs and that its
quantities are internally consistent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mmlsa.chunking import chunk_text
from mmlsa.distance.fwed import FunctionWordEditDistance
from mmlsa.distance.tokenize import load_function_words
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger, read_ledger, summarize
from mmlsa.llm.providers.fake import FakeProvider
from mmlsa.llm.runner import Runner
from mmlsa.pipeline.classify import classify, compute_threshold
from mmlsa.pipeline.profile import extract_profile
from mmlsa.pipeline.rewrite import report_creation, rewrite_chunks, to_chunk_deltas
from mmlsa.pipeline.score import aggregate_creation, aggregate_run, scorable_scores
from mmlsa.reporting.tables import scores_frame, write_scores_csv
from tests.conftest import REPO_ROOT

MINI_CORPUS = REPO_ROOT / "tests" / "fixtures" / "mini_corpus"
FUNCTION_WORDS = str(REPO_ROOT / "data" / "function_words" / "en_core_v1.txt")

CHUNK_SIZE = 60
RUNS = 2


@pytest.fixture(scope="module")
def corpus() -> dict[str, str]:
    """The three development texts."""
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(MINI_CORPUS.glob("*.txt"))}


def run_pipeline(corpus: dict[str, str], root: Path, runs: int = RUNS) -> dict:
    """Steps 1 to 6 over a corpus, returning everything the artifacts would hold."""
    distance = FunctionWordEditDistance(FUNCTION_WORDS)
    function_words = frozenset(load_function_words(FUNCTION_WORDS))

    runner = Runner(
        provider=FakeProvider(),
        cache=ResponseCache(root / "cache"),
        ledger=Ledger(root / "runs" / "mini" / "calls.jsonl", run_id="mini"),
        concurrency=4,
    )

    chunks = {name: chunk_text(text, CHUNK_SIZE, creation_id=name) for name, text in corpus.items()}
    per_run: dict[str, list] = {name: [] for name in corpus}
    reports = []
    profiles = []

    for run_index in range(1, runs + 1):
        # Step 1. Each run re-extracts its own profile, which is what the averaging cancels.
        profile = extract_profile(corpus, runner, run_index=run_index)
        profiles.append(profile)

        for name, creation_chunks in chunks.items():
            # Step 3, then Step 4 inside to_chunk_deltas.
            rewrites = rewrite_chunks(
                creation_chunks,
                profile.profile.render(),
                runner,
                function_words,
                run_index=run_index,
            )
            reports.append(report_creation(name, run_index, rewrites))
            # Step 5, within the run.
            per_run[name].append(
                aggregate_run(name, run_index, to_chunk_deltas(rewrites, distance))
            )

    # Step 5, across runs.
    creations = [aggregate_creation(name, run_scores) for name, run_scores in per_run.items()]

    # Step 6.
    ids, scores = scorable_scores(creations)
    threshold = compute_threshold(scores)
    classification = classify(ids, scores, threshold)

    return {
        "runner": runner,
        "chunks": chunks,
        "profiles": profiles,
        "reports": reports,
        "creations": creations,
        "threshold": threshold,
        "classification": classification,
    }


# ------------------------------------------------------------------------------------ it runs


def test_the_whole_pipeline_runs_offline(corpus: dict[str, str], tmp_path: Path) -> None:
    """Six steps, three creations, two runs, no network and no API key."""
    result = run_pipeline(corpus, tmp_path)

    assert len(result["profiles"]) == RUNS
    assert len(result["creations"]) == 3
    assert all(creation.scorable for creation in result["creations"])


def test_every_chunk_of_every_creation_is_rewritten_in_every_run(
    corpus: dict[str, str], tmp_path: Path
) -> None:
    """Full coverage survives all the way through Step 3."""
    result = run_pipeline(corpus, tmp_path)

    for report in result["reports"]:
        assert report.n_failed == 0
        assert report.n_ok == report.n_chunks == len(result["chunks"][report.creation_id])


def test_each_creation_is_scored_in_every_run(corpus: dict[str, str], tmp_path: Path) -> None:
    """`M` per-run scores per creation, which is what Step 5 averages."""
    for creation in run_pipeline(corpus, tmp_path)["creations"]:
        assert creation.n_runs_scored == RUNS
        assert len(creation.per_run) == RUNS
        assert creation.score_std is not None


def test_the_deltas_are_neither_all_zero_nor_degenerate(
    corpus: dict[str, str], tmp_path: Path
) -> None:
    """The property `FakeProvider` exists to guarantee.

    If this fails, every downstream assertion in the suite is passing vacuously on a pipeline that
    measures nothing.
    """
    scores = [creation.score for creation in run_pipeline(corpus, tmp_path)["creations"]]

    assert all(0.0 < score < 1.0 for score in scores)
    assert len(set(scores)) == len(scores)


# -------------------------------------------------------------------------------- consistency


def test_two_runs_with_the_same_inputs_produce_identical_scores(
    corpus: dict[str, str], tmp_path: Path
) -> None:
    """Reproducibility end to end, which is what the run artifacts inherit."""
    first = run_pipeline(corpus, tmp_path / "a")
    second = run_pipeline(corpus, tmp_path / "b")

    assert [c.score for c in first["creations"]] == [c.score for c in second["creations"]]
    assert first["threshold"].tau == second["threshold"].tau


def test_a_replayed_run_costs_no_calls(corpus: dict[str, str], tmp_path: Path) -> None:
    """Everything goes through the cache, Step 1 and Step 3 alike."""
    first = run_pipeline(corpus, tmp_path)
    issued = first["runner"].stats.live

    second = run_pipeline(corpus, tmp_path)

    assert issued > 0
    assert second["runner"].stats.live == 0
    assert second["runner"].stats.cached > 0


def test_every_call_is_in_the_ledger(corpus: dict[str, str], tmp_path: Path) -> None:
    """R2, over a complete run rather than a unit test."""
    result = run_pipeline(corpus, tmp_path)
    entries = read_ledger(tmp_path / "runs" / "mini" / "calls.jsonl")
    summary = summarize(entries)

    assert summary.total == result["runner"].stats.submitted
    assert set(summary.by_tag) <= {"profile", "profile_merge", "rewrite"}
    assert summary.by_tag["rewrite"] > 0


def test_every_score_traces_back_to_its_chunks(corpus: dict[str, str], tmp_path: Path) -> None:
    """R7: interpretability is a chain from the reported number to the calls behind it."""
    result = run_pipeline(corpus, tmp_path)

    for creation in result["creations"]:
        counts = creation.diagnostics["n_chunks_total"]
        assert len(counts) == RUNS
        assert all(count == len(result["chunks"][creation.creation_id]) for count in counts)


# ------------------------------------------------------------------------------- the artifacts


def test_the_run_produces_the_reportable_artifacts(corpus: dict[str, str], tmp_path: Path) -> None:
    """What a reader is handed at the end."""
    result = run_pipeline(corpus, tmp_path)

    frame = scores_frame(result["creations"], result["classification"])
    path = write_scores_csv(frame, tmp_path / "scores.csv")

    assert path.is_file()
    assert len(frame) == 3
    assert set(frame["label"]) <= {"authentic", "suspicious"}
    assert frame["score_mean"].notna().all()


def test_the_classification_covers_every_creation(corpus: dict[str, str], tmp_path: Path) -> None:
    """Nothing may fall between the two labels."""
    result = run_pipeline(corpus, tmp_path)
    classification = result["classification"]

    assert len(classification.labels) == 3
    assert len(classification.suspicious) + len(classification.authentic) == 3


def test_a_short_corpus_still_yields_a_threshold(corpus: dict[str, str], tmp_path: Path) -> None:
    """Three points is the smallest case Step 6 will ever see, and it must not crash on it."""
    threshold = run_pipeline(corpus, tmp_path)["threshold"]

    assert 0.0 <= threshold.tau <= 1.0
    assert threshold.method == "otsu_exact"
    assert "flags" in threshold.diagnostics
