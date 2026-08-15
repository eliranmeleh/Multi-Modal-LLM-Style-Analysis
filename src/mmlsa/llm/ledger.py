"""The append-only call ledger.

Non-functional requirement Auditability (R2): every LLM call is logged with its prompt, response,
model id, model version, parameters, token usage, latency and UTC timestamp. ``docs/PROMPTS.md``
section 6 commits the project to publishing the actual bytes sent, not merely the templates, so the
rendered prompt is written in full.

**Cache hits are logged too.** A ledger that recorded only the calls that reached the network would
describe the first run and no other, and could not be used to reconstruct what a resumed run did.
Every line carries ``cached``, so the two are distinguishable without being separated.

One JSON object per line, appended and flushed immediately. A killed run leaves a valid ledger up to
its last completed call, which is exactly what a resume needs to be checkable.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mmlsa.llm.base import LLMRequest, LLMResponse
from mmlsa.utils.hashing import hash_text

LEDGER_SCHEMA_VERSION = 1

REQUIRED_FIELDS = (
    "schema_version",
    "ts_utc",
    "run_id",
    "cache_key",
    "tag",
    "provider",
    "model_id",
    "cached",
    "status",
    "attempt",
    "prompt",
    "prompt_sha256",
)
"""Fields every line must carry. Asserted by ``validate_line`` and by the ledger tests."""


@dataclass
class LedgerEntry:
    """One recorded call. Written verbatim as a JSON line."""

    schema_version: int
    ts_utc: str
    run_id: str
    cache_key: str
    tag: str
    provider: str
    model_id: str
    cached: bool
    status: str
    attempt: int

    prompt: str
    prompt_sha256: str
    system: str | None = None
    temperature: float = 0.0
    max_output_tokens: int = 0
    response_format: str = "text"
    prompt_schema_version: int = 1

    creation_id: str = ""
    chunk_index: int | None = None
    run_index: int | None = None

    response: str = ""
    response_sha256: str = ""
    model_version: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str = ""
    error: str = ""
    error_class: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Plain data for serialization."""
        return asdict(self)


def build_entry(
    *,
    run_id: str,
    cache_key: str,
    request: LLMRequest,
    provider: str,
    model_id: str,
    cached: bool,
    status: str,
    attempt: int = 1,
    response: LLMResponse | None = None,
    creation_id: str = "",
    chunk_index: int | None = None,
    run_index: int | None = None,
    error: str = "",
    error_class: str = "",
    timestamp: str | None = None,
) -> LedgerEntry:
    """Assemble a ledger entry from a request and its outcome."""
    return LedgerEntry(
        schema_version=LEDGER_SCHEMA_VERSION,
        ts_utc=timestamp or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        run_id=run_id,
        cache_key=cache_key,
        tag=request.tag,
        provider=provider,
        model_id=model_id,
        cached=cached,
        status=status,
        attempt=attempt,
        prompt=request.prompt,
        prompt_sha256=hash_text(request.prompt),
        system=request.system,
        temperature=request.temperature,
        max_output_tokens=request.max_output_tokens,
        response_format=request.response_format,
        prompt_schema_version=request.prompt_schema_version,
        creation_id=creation_id,
        chunk_index=chunk_index,
        run_index=run_index,
        response=response.text if response else "",
        response_sha256=hash_text(response.text) if response else "",
        model_version=response.model_version if response else "",
        input_tokens=response.input_tokens if response else 0,
        output_tokens=response.output_tokens if response else 0,
        latency_ms=response.latency_ms if response else 0,
        finish_reason=response.finish_reason if response else "",
        error=error,
        error_class=error_class,
    )


class Ledger:
    """Append-only writer for ``runs/<run_id>/calls.jsonl``.

    Thread-safe: the runner writes from a worker pool, and interleaved partial lines would corrupt
    the file. A lock around a single ``write`` plus ``flush`` is sufficient and costs nothing at this
    call volume.
    """

    def __init__(self, path: Path, run_id: str) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._count = 0

    @property
    def count(self) -> int:
        """How many lines this instance has written."""
        return self._count

    def append(self, entry: LedgerEntry) -> None:
        """Write one entry and flush it to the operating system immediately."""
        line = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True)
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")
            stream.flush()
            self._count += 1


def read_ledger(path: Path) -> list[dict[str, Any]]:
    """Read a ledger back, skipping a trailing partial line.

    A run killed mid-write can leave one incomplete final line. Everything before it is intact and
    usable, so the last line is dropped rather than the whole file being rejected.
    """
    if not Path(path).is_file():
        return []

    entries: list[dict[str, Any]] = []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                break
            raise
    return entries


def validate_line(entry: dict[str, Any]) -> list[str]:
    """Check one ledger line against the schema. Returns the problems, empty if valid."""
    problems = [f"missing field '{name}'" for name in REQUIRED_FIELDS if name not in entry]

    if entry.get("schema_version") != LEDGER_SCHEMA_VERSION:
        problems.append(
            f"schema_version is {entry.get('schema_version')}, expected {LEDGER_SCHEMA_VERSION}"
        )
    if entry.get("status") not in {"ok", "failed"}:
        problems.append(f"status '{entry.get('status')}' is not 'ok' or 'failed'")
    if not isinstance(entry.get("cached"), bool):
        problems.append("cached is not a boolean")
    if entry.get("status") == "ok" and not entry.get("response_sha256"):
        problems.append("a successful call recorded no response hash")
    if entry.get("prompt") and entry.get("prompt_sha256") != hash_text(entry["prompt"]):
        problems.append("prompt_sha256 does not match the recorded prompt")

    return problems


@dataclass
class LedgerSummary:
    """Aggregate view of a ledger, for the run manifest and the runbook."""

    total: int = 0
    cached: int = 0
    live: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_tag: dict[str, int] = field(default_factory=dict)


def summarize(entries: list[dict[str, Any]]) -> LedgerSummary:
    """Summarize a ledger's contents."""
    summary = LedgerSummary(total=len(entries))
    for entry in entries:
        if entry.get("status") == "failed":
            summary.failed += 1
        if entry.get("cached"):
            summary.cached += 1
        else:
            summary.live += 1
        summary.input_tokens += entry.get("input_tokens", 0)
        summary.output_tokens += entry.get("output_tokens", 0)
        tag = entry.get("tag", "")
        summary.by_tag[tag] = summary.by_tag.get(tag, 0) + 1
    return summary
