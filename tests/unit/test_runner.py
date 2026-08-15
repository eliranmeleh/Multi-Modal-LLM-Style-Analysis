"""The runner: cache integration, ordering, retries, rate limiting and failure handling."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from mmlsa.llm.base import (
    CacheMissError,
    LLMRequest,
    LLMResponse,
    PermanentProviderError,
    TransientProviderError,
)
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger, read_ledger, validate_line
from mmlsa.llm.providers.fake import FakeProvider
from mmlsa.llm.runner import Job, Runner, TokenBucket


class CountingProvider:
    """Wraps a provider and counts calls, optionally failing a set number of times first."""

    name = "fake"

    def __init__(self, failures: int = 0, error: type[Exception] = TransientProviderError) -> None:
        self._inner = FakeProvider()
        self.model_id = self._inner.model_id
        self.calls = 0
        self._remaining_failures = failures
        self._error = error
        self._lock = threading.Lock()

    def context_window(self) -> int:
        return self._inner.context_window()

    def complete(self, request: LLMRequest) -> LLMResponse:
        with self._lock:
            self.calls += 1
            if self._remaining_failures > 0:
                self._remaining_failures -= 1
                raise self._error("injected failure")
        return self._inner.complete(request)


def make_runner(tmp_path: Path, provider=None, **options) -> Runner:
    """A runner wired to a fresh cache and ledger under ``tmp_path``."""
    return Runner(
        provider=provider or CountingProvider(),
        cache=ResponseCache(tmp_path / "cache", mode=options.pop("mode", "live")),
        ledger=Ledger(tmp_path / "runs" / "r1" / "calls.jsonl", run_id="r1"),
        mode=options.pop("runner_mode", "live"),
        **options,
    )


def rewrite_job(index: int, creation: str = "text_a") -> Job:
    """One rewrite job, with a prompt distinct per creation and chunk."""
    return Job(
        request=LLMRequest(
            prompt=f"Passage to rewrite:\n{creation} chunk {index} you have your will",
            tag="rewrite",
        ),
        creation_id=creation,
        chunk_index=index,
    )


# -------------------------------------------------------------------------------- the cache path


def test_the_same_request_twice_issues_one_provider_call(tmp_path: Path) -> None:
    """The acceptance criterion, and the reason a re-run is free."""
    provider = CountingProvider()
    runner = make_runner(tmp_path, provider, concurrency=1)

    first = runner.run([rewrite_job(0)])
    second = runner.run([rewrite_job(0)])

    assert provider.calls == 1
    assert first[0].cached is False
    assert second[0].cached is True
    assert first[0].response.text == second[0].response.text


def test_a_cache_hit_is_still_recorded_in_the_ledger(tmp_path: Path) -> None:
    """A ledger that logged only network calls would describe the first run and no other."""
    runner = make_runner(tmp_path, concurrency=1)
    runner.run([rewrite_job(0)])
    runner.run([rewrite_job(0)])

    lines = read_ledger(runner.ledger.path)

    assert len(lines) == 2
    assert [line["cached"] for line in lines] == [False, True]
    assert all(validate_line(line) == [] for line in lines)


def test_every_outcome_produces_exactly_one_ledger_line(tmp_path: Path) -> None:
    """One line per call, so counting lines counts calls."""
    runner = make_runner(tmp_path, concurrency=1)
    runner.run([rewrite_job(i) for i in range(5)])

    assert len(read_ledger(runner.ledger.path)) == 5


def test_changing_the_prompt_schema_version_forces_a_new_call(tmp_path: Path) -> None:
    """Editing a template must invalidate its entries."""
    from dataclasses import replace

    provider = CountingProvider()
    runner = make_runner(tmp_path, provider, concurrency=1)

    job = rewrite_job(0)
    runner.run([job])
    runner.run(
        [
            Job(
                request=replace(job.request, prompt_schema_version=2),
                creation_id="text_a",
                chunk_index=0,
            )
        ]
    )

    assert provider.calls == 2


# ------------------------------------------------------------------------------------- ordering


def test_results_come_back_in_deterministic_order_whatever_the_completion_order(
    tmp_path: Path,
) -> None:
    """Sorted by creation then chunk, so a downstream mean cannot depend on thread scheduling."""
    runner = make_runner(tmp_path, concurrency=8)

    jobs = [
        rewrite_job(i, creation) for creation in ("text_c", "text_a", "text_b") for i in (2, 0, 1)
    ]
    results = runner.run(jobs)

    ordering = [(r.job.creation_id, r.job.chunk_index) for r in results]
    assert ordering == sorted(ordering)


def test_two_runs_over_the_same_jobs_agree_exactly(tmp_path: Path) -> None:
    """Reproducibility at the runner level, which is what the run artifacts inherit."""
    jobs = [rewrite_job(i) for i in range(12)]

    first = [r.response.text for r in make_runner(tmp_path / "a", concurrency=8).run(jobs)]
    second = [r.response.text for r in make_runner(tmp_path / "b", concurrency=8).run(jobs)]

    assert first == second


def test_an_empty_job_list_is_not_an_error(tmp_path: Path) -> None:
    """A subset that selects nothing should produce nothing, not raise."""
    assert make_runner(tmp_path).run([]) == []


def test_identical_prompts_across_creations_race_on_one_cache_entry_safely(tmp_path: Path) -> None:
    """Content addressing means duplicate prompts collide by design, and workers race to write.

    Two creations can legitimately contain the same passage, and every retry re-enters the same key.
    Whoever wins the race, the payload is equivalent, because the key is a function of the request.
    This failed on Windows before the write was made race-tolerant.
    """
    shared = LLMRequest(prompt="Passage to rewrite:\nyou have your will", tag="rewrite")
    jobs = [
        Job(request=shared, creation_id=f"text_{index:02d}", chunk_index=0) for index in range(24)
    ]

    runner = make_runner(tmp_path, concurrency=8)
    results = runner.run(jobs)

    assert all(result.ok for result in results)
    assert len({result.response.text for result in results}) == 1
    assert runner.cache.count() == 1
    assert not list(runner.cache.root.rglob("*.tmp"))


# -------------------------------------------------------------------------------------- retries


def test_a_transient_failure_is_retried_and_then_succeeds(tmp_path: Path) -> None:
    """Rate limits and 5xx are normal at this call volume, not run-ending."""
    provider = CountingProvider(failures=2)
    runner = make_runner(tmp_path, provider, concurrency=1, max_transient_retries=5)

    results = runner.run([rewrite_job(0)])

    assert results[0].ok
    assert provider.calls == 3
    assert runner.stats.retries == 2


def test_exhausting_the_retry_budget_marks_the_job_failed_without_aborting_the_run(
    tmp_path: Path,
) -> None:
    """A run fifty minutes in must not die because one chunk is cursed."""
    provider = CountingProvider(failures=99)
    runner = make_runner(tmp_path, provider, concurrency=1, max_transient_retries=2)

    results = runner.run([rewrite_job(0), rewrite_job(1)])

    assert all(not result.ok for result in results)
    assert all(result.error for result in results)
    assert runner.stats.failed == 2
    assert provider.calls == 6


def test_a_permanent_failure_is_not_retried(tmp_path: Path) -> None:
    """Retrying bad credentials wastes five backoffs to reach the same answer."""
    provider = CountingProvider(failures=99, error=PermanentProviderError)
    runner = make_runner(tmp_path, provider, concurrency=1, max_transient_retries=5)

    results = runner.run([rewrite_job(0)])

    assert not results[0].ok
    assert provider.calls == 1
    assert results[0].error_class == "PermanentProviderError"


def test_a_failure_is_recorded_in_the_ledger(tmp_path: Path) -> None:
    """Never swallow a provider exception without recording it."""
    provider = CountingProvider(failures=99, error=PermanentProviderError)
    runner = make_runner(tmp_path, provider, concurrency=1)
    runner.run([rewrite_job(0)])

    line = read_ledger(runner.ledger.path)[0]

    assert line["status"] == "failed"
    assert line["error_class"] == "PermanentProviderError"
    assert validate_line(line) == []


def test_a_failed_call_is_not_cached(tmp_path: Path) -> None:
    """Caching a failure would make it permanent across every future run."""
    provider = CountingProvider(failures=99)
    runner = make_runner(tmp_path, provider, concurrency=1, max_transient_retries=1)
    runner.run([rewrite_job(0)])

    assert runner.cache.count() == 0


# ---------------------------------------------------------------------------------- replay mode


def test_replay_mode_raises_on_a_cache_miss(tmp_path: Path) -> None:
    """A published run reproduces from its artifacts or says plainly that it cannot."""
    runner = make_runner(tmp_path, concurrency=1, runner_mode="replay", mode="replay")

    with pytest.raises(CacheMissError, match="replay mode"):
        runner.run([rewrite_job(0)])


def test_replay_mode_serves_a_recorded_call_without_touching_the_provider(tmp_path: Path) -> None:
    """The positive half: what was recorded comes back, at no cost."""
    live_provider = CountingProvider()
    make_runner(tmp_path, live_provider, concurrency=1).run([rewrite_job(0)])

    replay_provider = CountingProvider()
    replay = make_runner(
        tmp_path, replay_provider, concurrency=1, runner_mode="replay", mode="replay"
    )
    results = replay.run([rewrite_job(0)])

    assert results[0].cached is True
    assert replay_provider.calls == 0


def test_a_replay_miss_is_recorded_before_it_raises(tmp_path: Path) -> None:
    """The ledger should show what was asked for and could not be served."""
    runner = make_runner(tmp_path, concurrency=1, runner_mode="replay", mode="replay")

    with pytest.raises(CacheMissError):
        runner.run([rewrite_job(0)])

    line = read_ledger(runner.ledger.path)[0]
    assert line["status"] == "failed"
    assert line["error_class"] == "CacheMissError"


# ------------------------------------------------------------------------------- rate limiting


def test_the_token_bucket_limits_the_rate() -> None:
    """Two tokens of capacity refilling at 10 per second: the third acquire must wait."""
    bucket = TokenBucket(capacity=2, refill_per_second=10.0)

    started = time.monotonic()
    for _ in range(4):
        bucket.acquire(1.0)
    elapsed = time.monotonic() - started

    assert elapsed >= 0.15


def test_the_token_bucket_allows_a_burst_up_to_capacity() -> None:
    """Capacity is what makes a burst possible; without it throughput would be needlessly serial."""
    bucket = TokenBucket(capacity=10, refill_per_second=1.0)

    started = time.monotonic()
    for _ in range(10):
        bucket.acquire(1.0)

    assert time.monotonic() - started < 0.1


def test_a_request_larger_than_the_whole_budget_does_not_deadlock() -> None:
    """Clamped rather than refused: refusing here would stall a run permanently."""
    bucket = TokenBucket(capacity=5, refill_per_second=100.0)

    bucket.acquire(500.0, timeout=5.0)


def test_the_token_bucket_is_thread_safe() -> None:
    """Workers share it, and a lost update would silently exceed the provider's limit."""
    from concurrent.futures import ThreadPoolExecutor

    bucket = TokenBucket(capacity=100, refill_per_second=1000.0)
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda _: bucket.acquire(1.0), range(100)))

    assert bucket._tokens <= 100


# ---------------------------------------------------------------------------------- statistics


def test_statistics_distinguish_cached_live_and_failed(tmp_path: Path) -> None:
    """What the end-of-run log line and the run manifest report."""
    provider = CountingProvider()
    runner = make_runner(tmp_path, provider, concurrency=1)

    runner.run([rewrite_job(0), rewrite_job(1)])
    runner.run([rewrite_job(0)])

    assert runner.stats.live == 2
    assert runner.stats.cached == 1
    assert runner.stats.failed == 0
    assert runner.stats.submitted == 3
