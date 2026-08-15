"""A provider that serves only from the recorded cache, and refuses to invent anything.

Selected with ``llm.provider: replay``, and equivalent to running any provider under
``llm.mode: replay``. Both paths exist because they answer different questions: the mode says "do not
call out during this run", and the provider says "this configuration has no live backend at all",
which is what a published artifact should look like when someone else clones it.

A miss is a hard error. That is the entire value of the thing: reproducing a published run must
either give the recorded answer or say plainly that it cannot.
"""

from __future__ import annotations

from typing import Any

from mmlsa.llm.base import CacheMissError, LLMRequest, LLMResponse
from mmlsa.llm.cache import ResponseCache


class ReplayProvider:
    """Returns recorded responses; raises ``CacheMissError`` for anything not on disk."""

    name = "replay"

    def __init__(
        self,
        cache: ResponseCache,
        model_id: str | None = None,
        context_window: int = 1_000_000,
        **_: Any,
    ) -> None:
        self._cache = cache
        self.model_id = model_id or "replay"
        self._context_window = context_window
        self.calls = 0

    def context_window(self) -> int:
        """Taken from configuration, since there is no live model to ask."""
        return self._context_window

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return the recorded response for this request, or refuse.

        The key is computed against the **originating** provider's name where one is recorded,
        because a response cached from a live run belongs to that provider's namespace. In practice
        the runner consults the cache first and this method is only reached on a miss, so the lookup
        here is a second line of defence rather than the normal path.
        """
        self.calls += 1

        key = ResponseCache.key_for(self.name, self.model_id, request)
        recorded = self._cache.get(key)
        if recorded is not None:
            return recorded

        raise CacheMissError(
            f"no recorded response for this request (key {key[:12]}, tag '{request.tag}'). "
            "Replay cannot issue a live call. Either the cache is incomplete, or the prompt, the "
            "model or a prompt_schema_version has changed since the run was recorded."
        )
