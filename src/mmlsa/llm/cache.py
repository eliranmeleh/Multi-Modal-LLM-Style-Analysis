"""The content-addressed response cache.

This is the load-bearing piece of the architecture (``docs/DECISIONS.md`` I1). A full run is roughly
7,500 calls, and this one mechanism delivers four things that would otherwise each need their own:

*Resumability.* Re-invoking an interrupted run skips every completed call. There is no separate
checkpoint mechanism because none is needed.

*Reproducibility.* A recorded run replays offline, byte for byte, with no network.

*Auditability.* Every response ever received is on disk, addressed by exactly what was asked.

*Free re-runs.* Changing the aggregation or the threshold costs nothing, because the expensive part
is already stored.

The key is a sha256 over canonical JSON of the fields that determine the answer. It is stable across
processes and machines by construction: no timestamps, no paths, no dictionary ordering.

See ``docs/ARCHITECTURE.md`` section 4.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mmlsa.llm.base import CacheMissError, LLMRequest, LLMResponse
from mmlsa.utils.hashing import hash_payload

CACHE_FORMAT_VERSION = 1


@dataclass
class CacheStats:
    """Counters for one process's use of the cache."""

    hits: int = 0
    misses: int = 0
    writes: int = 0
    corrupt: int = 0

    @property
    def lookups(self) -> int:
        """Total reads attempted."""
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        """Share of lookups served from disk."""
        return self.hits / self.lookups if self.lookups else 0.0


class ResponseCache:
    """A content-addressed store of provider responses.

    Modes, from ``llm.mode``:

    ``live``     a miss calls the provider and the response is written.
    ``replay``   a miss is a hard error. Nothing is ever called or written.
    ``refresh``  the cache is not read at all; every call is made and overwrites.
    """

    def __init__(self, root: Path, *, mode: str = "live") -> None:
        if mode not in {"live", "replay", "refresh"}:
            raise ValueError(f"unknown cache mode '{mode}'. Expected live, replay or refresh.")
        self.root = Path(root)
        self.mode = mode
        self.stats = CacheStats()

    # -- addressing ---------------------------------------------------------------------------

    @staticmethod
    def key_for(provider_name: str, model_id: str, request: LLMRequest) -> str:
        """The cache key: sha256 over canonical JSON of everything that determines the answer."""
        return hash_payload(request.cache_fields(provider_name, model_id))

    def path_for(self, key: str) -> Path:
        """Where an entry lives. Sharded by the first two characters to keep directories small.

        A flat directory of 7,500 files is workable; several runs' worth is not, and some filesystems
        degrade badly. The shard costs nothing and removes the question.
        """
        return self.root / key[:2] / f"{key}.json"

    # -- reading and writing ------------------------------------------------------------------

    def get(self, key: str) -> LLMResponse | None:
        """Return a cached response, or None on a miss.

        In ``refresh`` mode this always reports a miss without touching the disk, which is what
        makes a deliberate re-measurement actually re-measure.
        """
        if self.mode == "refresh":
            self.stats.misses += 1
            return None

        path = self.path_for(key)
        if not path.is_file():
            self.stats.misses += 1
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            response = LLMResponse.from_dict(payload["response"])
        except (OSError, KeyError, json.JSONDecodeError):
            # A corrupt entry is a miss, not a crash. The response can always be fetched again, so
            # the cheap and safe response is to pay for one more call. It is counted rather than
            # ignored, because a rising corruption count means something is wrong with the disk or
            # with concurrent access, and that is worth seeing. In replay mode the miss becomes a
            # hard error one level up, which is the correct outcome there.
            self.stats.misses += 1
            self.stats.corrupt += 1
            return None

        self.stats.hits += 1
        return response

    def put(
        self,
        key: str,
        provider_name: str,
        model_id: str,
        request: LLMRequest,
        response: LLMResponse,
    ) -> Path:
        """Write an entry. Atomic, so an interrupted run never leaves a half-written response."""
        if self.mode == "replay":
            raise CacheMissError(
                "replay mode may not write to the cache; this indicates a call was attempted"
            )

        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "cache_format_version": CACHE_FORMAT_VERSION,
            "key": key,
            "provider": provider_name,
            "model_id": model_id,
            "model_version": response.model_version,
            "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "request": request.cache_fields(provider_name, model_id) | {"tag": request.tag},
            "response": response.to_dict(),
            "latency_ms": response.latency_ms,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        }

        self._write_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        self.stats.writes += 1
        return path

    @staticmethod
    def _write_atomic(path: Path, text: str) -> None:
        """Write via a temporary file in the same directory, then rename into place.

        A reader never sees a partial entry, and a killed run leaves no debris that could later be
        mistaken for a valid response.

        **Two writers may race for the same key, and that is normal.** The cache is addressed by
        content, so identical requests from different workers collide by design: the same chunk text
        appearing in two creations, or a retry overlapping its own first attempt. Whoever wins, the
        payload is equivalent, because the key is a function of the request.

        On Windows the loser of that race gets ``PermissionError`` from ``os.replace`` when the
        destination is momentarily open. That is a race, not a failure: if the destination exists
        afterwards, the entry is there and the write succeeded in every sense that matters.
        """
        handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
            try:
                Path(temporary).replace(path)
            except PermissionError:
                if not path.is_file():
                    raise
                Path(temporary).unlink(missing_ok=True)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    # -- housekeeping -------------------------------------------------------------------------

    def contains(self, key: str) -> bool:
        """Whether an entry exists, without counting a hit or a miss."""
        return self.path_for(key).is_file()

    def count(self) -> int:
        """How many entries the cache holds."""
        return sum(1 for _ in self.root.rglob("*.json")) if self.root.is_dir() else 0

    def size_bytes(self) -> int:
        """Total bytes on disk."""
        if not self.root.is_dir():
            return 0
        return sum(p.stat().st_size for p in self.root.rglob("*.json"))
