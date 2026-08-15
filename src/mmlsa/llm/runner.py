"""The one place that issues calls, and therefore the one place that owns concurrency.

Pipeline code submits work and gets results back in **deterministic order**, sorted by
``(creation_id, chunk_index)``, whatever order they actually completed in. That is what keeps two
runs with the same configuration and seed producing identical output despite a thread pool.

Everything else here exists because a run is several thousand calls and takes an hour:

* the cache is consulted first, so a resumed run pays only for what it has not already done;
* a token bucket keeps the request and token rates inside the provider's limits;
* transient failures back off exponentially with full jitter and are retried;
* a permanent failure is recorded and the unit of work is marked failed, rather than aborting a run
  that is fifty minutes in.

See ``docs/ARCHITECTURE.md`` sections 4 and 5.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from tenacity import RetryCallState, Retrying, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_exponential_jitter

from mmlsa.llm.base import (
    CacheMissError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    PermanentProviderError,
    ProviderError,
    TransientProviderError,
)
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import Ledger, build_entry
from mmlsa.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Job:
    """One unit of work, with the provenance that makes its result traceable (R7)."""

    request: LLMRequest
    creation_id: str = ""
    chunk_index: int | None = None
    run_index: int | None = None

    def sort_key(self) -> tuple[str, int, int]:
        """Deterministic ordering: by creation, then chunk, then run."""
        return (
            self.creation_id,
            self.chunk_index if self.chunk_index is not None else -1,
            self.run_index if self.run_index is not None else -1,
        )


@dataclass(frozen=True)
class JobResult:
    """The outcome of one job."""

    job: Job
    response: LLMResponse | None
    cached: bool
    attempts: int
    error: str = ""
    error_class: str = ""

    @property
    def ok(self) -> bool:
        """Whether a response was obtained at all."""
        return self.response is not None


@dataclass
class RunnerStats:
    """Counters for one call to :meth:`Runner.run`."""

    submitted: int = 0
    cached: int = 0
    live: int = 0
    failed: int = 0
    retries: int = 0
    by_error: dict[str, int] = field(default_factory=dict)


class TokenBucket:
    """A thread-safe token bucket, used for both the request and the token rate limits.

    Refills continuously rather than in discrete windows, so a burst at a window boundary cannot
    briefly double the effective rate, which is exactly the case providers respond to with a 429.
    """

    def __init__(self, capacity: float, refill_per_second: float) -> None:
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_second)
        self._tokens = float(capacity)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, amount: float = 1.0, *, timeout: float = 300.0) -> None:
        """Block until ``amount`` tokens are available, then take them."""
        if amount > self.capacity:
            # A single request larger than the whole budget would wait forever. Let it through and
            # let the provider be the judge; refusing here would deadlock the run.
            amount = self.capacity

        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.capacity, self._tokens + (now - self._updated) * self.refill_per_second
                )
                self._updated = now
                if self._tokens >= amount:
                    self._tokens -= amount
                    return
                shortfall = amount - self._tokens

            if time.monotonic() > deadline:
                raise TransientProviderError(
                    f"rate limiter timed out waiting for {amount:.0f} tokens"
                )
            time.sleep(min(shortfall / self.refill_per_second, 1.0))


class Runner:
    """Executes jobs through the cache, the rate limiter and the provider, and records every one."""

    def __init__(
        self,
        provider: LLMProvider,
        cache: ResponseCache,
        ledger: Ledger,
        *,
        concurrency: int = 8,
        requests_per_minute: int = 240,
        tokens_per_minute: int = 1_000_000,
        max_transient_retries: int = 5,
        mode: str = "live",
        progress: bool = False,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.ledger = ledger
        self.concurrency = max(1, concurrency)
        self.max_transient_retries = max_transient_retries
        self.mode = mode
        self.progress = progress
        self.stats = RunnerStats()

        self._requests = TokenBucket(requests_per_minute, requests_per_minute / 60.0)
        self._tokens = TokenBucket(tokens_per_minute, tokens_per_minute / 60.0)
        self._stats_lock = threading.Lock()

    # -- public surface -------------------------------------------------------------------------

    def run(self, jobs: Sequence[Job]) -> list[JobResult]:
        """Execute every job and return the results in deterministic order.

        Ordering is imposed here rather than left to completion order, so that a downstream mean or
        a written artifact cannot depend on which worker happened to finish first.
        """
        ordered = sorted(jobs, key=lambda job: job.sort_key())
        self.stats.submitted += len(ordered)

        if not ordered:
            return []

        if self.concurrency == 1:
            results = [self._execute(job) for job in ordered]
        else:
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                results = list(pool.map(self._execute, ordered))

        logger.info(
            "runner.complete",
            submitted=len(ordered),
            cached=self.stats.cached,
            live=self.stats.live,
            failed=self.stats.failed,
            retries=self.stats.retries,
        )
        return results

    def complete(self, request: LLMRequest, **provenance: Any) -> JobResult:
        """Execute a single request. Convenience for the corpus-level calls in Step 1."""
        return self._execute(Job(request=request, **provenance))

    # -- execution ------------------------------------------------------------------------------

    def _execute(self, job: Job) -> JobResult:
        """Serve one job from the cache if possible, otherwise call the provider."""
        key = ResponseCache.key_for(self.provider.name, self.provider.model_id, job.request)

        cached = self.cache.get(key)
        if cached is not None:
            self._count(cached=True)
            self._record(job, key, cached=True, status="ok", response=cached)
            return JobResult(job=job, response=cached, cached=True, attempts=0)

        if self.mode == "replay":
            message = (
                f"cache miss in replay mode (key {key[:12]}, tag '{job.request.tag}'). "
                "A published run must reproduce from its recorded artifacts; refusing to call out."
            )
            self._count(failed=True, error_class="CacheMissError")
            self._record(
                job, key, cached=False, status="failed", error=message, error_class="CacheMissError"
            )
            raise CacheMissError(message)

        return self._call_provider(job, key)

    def _call_provider(self, job: Job, key: str) -> JobResult:
        """Call the provider with rate limiting and bounded retries on transient failures."""
        estimated_tokens = float(len(job.request.prompt.split()) + job.request.max_output_tokens)
        attempts = 0

        try:
            for attempt in Retrying(
                stop=stop_after_attempt(self.max_transient_retries + 1),
                wait=wait_exponential_jitter(initial=1.0, max=60.0, jitter=2.0),
                retry=retry_if_exception_type(TransientProviderError),
                before_sleep=self._on_retry,
                reraise=True,
            ):
                with attempt:
                    attempts = attempt.retry_state.attempt_number
                    self._requests.acquire(1.0)
                    self._tokens.acquire(estimated_tokens)
                    response = self.provider.complete(job.request)
        except ProviderError as exc:
            message = f"{type(exc).__name__}: {exc}"
            self._count(failed=True, error_class=type(exc).__name__)
            self._record(
                job,
                key,
                cached=False,
                status="failed",
                attempt=attempts,
                error=str(exc),
                error_class=type(exc).__name__,
            )
            logger.warning(
                "runner.call_failed",
                tag=job.request.tag,
                creation_id=job.creation_id,
                chunk_index=job.chunk_index,
                error=message,
            )
            return JobResult(
                job=job,
                response=None,
                cached=False,
                attempts=attempts,
                error=str(exc),
                error_class=type(exc).__name__,
            )

        self.cache.put(key, self.provider.name, self.provider.model_id, job.request, response)
        self._count(live=True)
        self._record(job, key, cached=False, status="ok", attempt=attempts, response=response)
        return JobResult(job=job, response=response, cached=False, attempts=attempts)

    def _on_retry(self, state: RetryCallState) -> None:
        """Count a retry and say why, so a slow run is explainable from the log alone."""
        with self._stats_lock:
            self.stats.retries += 1
        logger.info(
            "runner.retry",
            attempt=state.attempt_number,
            sleeping=round(state.next_action.sleep, 2) if state.next_action else 0,
            error=str(state.outcome.exception()) if state.outcome else "",
        )

    # -- bookkeeping ----------------------------------------------------------------------------

    def _count(
        self,
        *,
        cached: bool = False,
        live: bool = False,
        failed: bool = False,
        error_class: str = "",
    ) -> None:
        """Update the counters under a lock, since workers share them."""
        with self._stats_lock:
            self.stats.cached += int(cached)
            self.stats.live += int(live)
            self.stats.failed += int(failed)
            if error_class:
                self.stats.by_error[error_class] = self.stats.by_error.get(error_class, 0) + 1

    def _record(
        self,
        job: Job,
        key: str,
        *,
        cached: bool,
        status: str,
        response: LLMResponse | None = None,
        attempt: int = 1,
        error: str = "",
        error_class: str = "",
    ) -> None:
        """Append one ledger line. Called for every outcome, cache hits included (R2)."""
        self.ledger.append(
            build_entry(
                run_id=self.ledger.run_id,
                cache_key=key,
                request=job.request,
                provider=self.provider.name,
                model_id=self.provider.model_id,
                cached=cached,
                status=status,
                attempt=attempt,
                response=response,
                creation_id=job.creation_id,
                chunk_index=job.chunk_index,
                run_index=job.run_index,
                error=error,
                error_class=error_class,
            )
        )


__all__ = [
    "Job",
    "JobResult",
    "PermanentProviderError",
    "Runner",
    "RunnerStats",
    "TokenBucket",
    "TransientProviderError",
]
