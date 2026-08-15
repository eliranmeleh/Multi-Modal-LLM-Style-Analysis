"""Resuming an interrupted run.

A full run is roughly 7,500 calls and takes around an hour. Anything that makes a crash cost a full
restart is unacceptable (``docs/ARCHITECTURE.md`` section 1), so resumability is a property the
project depends on rather than a convenience.

It is also the one property that is entirely emergent: there is no checkpoint code to test. It falls
out of the cache being consulted before every call. These tests exist to prove that it actually does.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from mmlsa.llm.base import LLMRequest, LLMResponse, TransientProviderError
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger, read_ledger, summarize
from mmlsa.llm.providers.fake import FakeProvider
from mmlsa.llm.runner import Job, Runner

TOTAL_JOBS = 40
KILL_AFTER = 17


class KillableProvider:
    """A provider that raises after a fixed number of calls, simulating a crash mid-run."""

    name = "fake"

    def __init__(self, die_after: int | None = None) -> None:
        self._inner = FakeProvider()
        self.model_id = self._inner.model_id
        self.calls = 0
        self._die_after = die_after
        self._lock = threading.Lock()

    def context_window(self) -> int:
        return self._inner.context_window()

    def complete(self, request: LLMRequest) -> LLMResponse:
        with self._lock:
            self.calls += 1
            if self._die_after is not None and self.calls > self._die_after:
                raise RunKilledError("simulated crash")
        return self._inner.complete(request)


class RunKilledError(Exception):
    """Stands in for the process being killed."""


def jobs(count: int = TOTAL_JOBS) -> list[Job]:
    """A run's worth of distinct rewrite jobs."""
    return [
        Job(
            request=LLMRequest(
                prompt=f"Passage to rewrite:\ncreation text_a chunk {index} you have your will",
                tag="rewrite",
            ),
            creation_id="text_a",
            chunk_index=index,
        )
        for index in range(count)
    ]


def build(tmp_path: Path, provider, run_id: str = "run_1", concurrency: int = 1) -> Runner:
    """A runner sharing one cache directory and one run directory across invocations."""
    return Runner(
        provider=provider,
        cache=ResponseCache(tmp_path / "cache"),
        ledger=Ledger(tmp_path / "runs" / run_id / "calls.jsonl", run_id=run_id),
        concurrency=concurrency,
    )


# --------------------------------------------------------------------------------- the property


def test_a_restarted_run_issues_only_the_remaining_calls(tmp_path: Path) -> None:
    """The acceptance criterion for M5.

    Kill the run after ``KILL_AFTER`` calls, restart it with the same run id, and assert that the
    second invocation calls the provider exactly the number of times still outstanding, not the
    total. This is the whole justification for putting a cache in front of every call.
    """
    first_provider = KillableProvider(die_after=KILL_AFTER)
    with pytest.raises(RunKilledError):
        build(tmp_path, first_provider).run(jobs())

    assert first_provider.calls == KILL_AFTER + 1

    second_provider = KillableProvider()
    results = build(tmp_path, second_provider).run(jobs())

    assert len(results) == TOTAL_JOBS
    assert all(result.ok for result in results)
    assert second_provider.calls == TOTAL_JOBS - KILL_AFTER


def test_a_third_run_issues_no_calls_at_all(tmp_path: Path) -> None:
    """Once complete, re-running is free, which is what makes re-analysis cheap."""
    build(tmp_path, KillableProvider()).run(jobs())

    third_provider = KillableProvider()
    results = build(tmp_path, third_provider).run(jobs())

    assert third_provider.calls == 0
    assert all(result.cached for result in results)


def test_the_resumed_run_produces_the_same_answers_as_an_uninterrupted_one(tmp_path: Path) -> None:
    """An interruption must not change the result, only the cost of getting it."""
    interrupted_provider = KillableProvider(die_after=KILL_AFTER)
    with pytest.raises(RunKilledError):
        build(tmp_path / "interrupted", interrupted_provider).run(jobs())
    resumed = build(tmp_path / "interrupted", KillableProvider()).run(jobs())

    clean = build(tmp_path / "clean", KillableProvider()).run(jobs())

    assert [r.response.text for r in resumed] == [r.response.text for r in clean]


def test_resumption_survives_a_change_of_concurrency(tmp_path: Path) -> None:
    """Restarting with a different worker count must not re-issue completed work."""
    first = KillableProvider(die_after=KILL_AFTER)
    with pytest.raises(RunKilledError):
        build(tmp_path, first, concurrency=1).run(jobs())

    second = KillableProvider()
    build(tmp_path, second, concurrency=8).run(jobs())

    assert second.calls <= TOTAL_JOBS - KILL_AFTER


# ----------------------------------------------------------------------------------- the record


def test_the_ledger_of_a_resumed_run_shows_both_halves(tmp_path: Path) -> None:
    """The audit trail must describe what the resumed run actually did, hits included."""
    with pytest.raises(RunKilledError):
        build(tmp_path, KillableProvider(die_after=KILL_AFTER)).run(jobs())
    build(tmp_path, KillableProvider()).run(jobs())

    summary = summarize(read_ledger(tmp_path / "runs" / "run_1" / "calls.jsonl"))

    assert summary.cached == KILL_AFTER
    assert summary.live == TOTAL_JOBS
    assert summary.total == KILL_AFTER + TOTAL_JOBS


def test_the_ledger_survives_the_interruption_intact(tmp_path: Path) -> None:
    """Appended and flushed per line, so a killed run leaves a readable record up to that point."""
    with pytest.raises(RunKilledError):
        build(tmp_path, KillableProvider(die_after=KILL_AFTER)).run(jobs())

    lines = read_ledger(tmp_path / "runs" / "run_1" / "calls.jsonl")

    assert len(lines) == KILL_AFTER
    assert all(line["status"] == "ok" for line in lines)


def test_the_cache_holds_exactly_the_completed_calls_after_an_interruption(tmp_path: Path) -> None:
    """No half-written entries, and nothing cached that was never answered."""
    with pytest.raises(RunKilledError):
        build(tmp_path, KillableProvider(die_after=KILL_AFTER)).run(jobs())

    cache = ResponseCache(tmp_path / "cache")

    assert cache.count() == KILL_AFTER
    assert not list(cache.root.rglob("*.tmp"))


def test_a_transient_failure_partway_through_does_not_lose_earlier_work(tmp_path: Path) -> None:
    """Work already completed stays completed even when a later job exhausts its retries."""

    class FlakyLater(KillableProvider):
        def complete(self, request: LLMRequest) -> LLMResponse:
            with self._lock:
                self.calls += 1
                if self.calls > KILL_AFTER:
                    raise TransientProviderError("still failing")
            return self._inner.complete(request)

    runner = Runner(
        provider=FlakyLater(),
        cache=ResponseCache(tmp_path / "cache"),
        ledger=Ledger(tmp_path / "runs" / "run_1" / "calls.jsonl", run_id="run_1"),
        concurrency=1,
        max_transient_retries=0,
    )
    results = runner.run(jobs())

    assert sum(1 for result in results if result.ok) == KILL_AFTER
    assert ResponseCache(tmp_path / "cache").count() == KILL_AFTER

    recovered = build(tmp_path, KillableProvider()).run(jobs())
    assert all(result.ok for result in recovered)
