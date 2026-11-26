"""Publishing a run and reproducing it from what was published (milestone M15).

``release`` packs finished runs into one archive: each run directory as it is, plus exactly the cache
entries its ledger used, so the archive is enough to replay the run without a key and without the
rest of the cache. A SHA-256 of the archive is written beside it.

``reproduce`` re-runs a finished run in replay mode from its own configuration snapshot, into a
scratch directory, and compares ``scores.csv`` and ``threshold.json`` byte for byte with the
original. That comparison is M15's acceptance test (``docs/PLAN.md``).
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from mmlsa.config import Config
from mmlsa.llm.cache import ResponseCache
from mmlsa.llm.ledger import read_ledger
from mmlsa.pipeline.orchestrator import execute_run, is_complete

COMPARED = ("scores.csv", "threshold.json")
"""The files a reproduction must match byte for byte."""


class ReleaseError(Exception):
    """Raised when a run cannot be packed or reproduced."""


# ------------------------------------------------------------------------------------- release


def used_cache_keys(run_dir: Path) -> list[str]:
    """The cache keys of every answered call in a run's ledger, in first-use order.

    A call that failed was never stored, so its key is left out; a call answered from the cache is
    kept, because a replay needs that answer too.
    """
    keys: dict[str, None] = {}
    for entry in read_ledger(run_dir / "calls.jsonl"):
        if entry.get("error"):
            continue
        key = entry.get("cache_key")
        if key:
            keys[key] = None
    return list(keys)


@dataclass(frozen=True)
class Release:
    """A written archive and what is in it."""

    archive: Path
    sha256: str
    run_ids: list[str]
    n_cache_entries: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build_release(
    config: Config, run_ids: Sequence[str], *, out_dir: Path | None = None, name: str = ""
) -> Release:
    """Write ``release/<name>.tar.gz`` holding the runs and the cache entries they used."""
    if not run_ids:
        raise ReleaseError("name at least one run to release")
    runs = config.path(config.run.out_dir)
    cache = ResponseCache(config.path(config.llm.cache_dir))
    keys: dict[str, None] = {}
    for run_id in run_ids:
        run_dir = runs / run_id
        if not is_complete(run_dir):
            raise ReleaseError(f"no finished run '{run_id}' under {runs}")
        keys.update(dict.fromkeys(used_cache_keys(run_dir)))
    missing = [key for key in keys if not cache.path_for(key).is_file()]
    if missing:
        raise ReleaseError(
            f"{len(missing)} cache entr{'y' if len(missing) == 1 else 'ies'} used by these runs "
            f"{'is' if len(missing) == 1 else 'are'} not in {cache.root} (first: {missing[0][:12]}). "
            "Point llm.cache_dir at the cache the runs were made with."
        )

    out = out_dir or config.root / "release"
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"{name or run_ids[0]}.tar.gz"
    if archive.exists():
        raise ReleaseError(f"{archive} exists; a release is never overwritten")

    readme = (
        "This archive holds finished runs and exactly the cached model answers they used.\n\n"
        "Unpack it in the repository root, so runs/ and cache/ land there, then run\n\n"
        "    python -m mmlsa reproduce --run-id <run_id>\n\n"
        "which replays the run from the cache, sends no request and needs no key, and compares\n"
        "scores.csv and threshold.json byte for byte with the released run.\n\n"
        f"Runs: {', '.join(run_ids)}\nCache entries: {len(keys)}\n"
    )
    with tarfile.open(archive, "w:gz") as tar:
        for run_id in run_ids:
            tar.add(runs / run_id, arcname=f"runs/{run_id}")
        for key in keys:
            tar.add(cache.path_for(key), arcname=f"cache/{key[:2]}/{key}.json")
        with tempfile.TemporaryDirectory() as scratch:
            note = Path(scratch) / "RELEASE.md"
            note.write_text(readme, encoding="utf-8", newline="\n")
            tar.add(note, arcname="RELEASE.md")

    sha = _sha256(archive)
    (out / f"{archive.name}.sha256").write_text(f"{sha}  {archive.name}\n", encoding="utf-8")
    return Release(archive=archive, sha256=sha, run_ids=list(run_ids), n_cache_entries=len(keys))


# ----------------------------------------------------------------------------------- reproduce


@dataclass
class Reproduction:
    """The outcome of replaying a run and comparing it with the original."""

    run_id: str
    replay_dir: Path
    matches: dict[str, bool] = field(default_factory=dict)

    @property
    def identical(self) -> bool:
        """Whether every compared file matched byte for byte."""
        return bool(self.matches) and all(self.matches.values())


def snapshot_config(config: Config, run_dir: Path) -> Config:
    """The configuration a run was made with, from its snapshot, bound to this project root."""
    snapshot = yaml.safe_load((run_dir / "config.snapshot.yaml").read_text(encoding="utf-8"))
    return Config.model_validate(snapshot).bind_root(config.root)


def reproduce_run(
    config: Config,
    run_id: str,
    *,
    out_dir: Path | None = None,
    progress: bool = False,
) -> Reproduction:
    """Replay ``run_id`` from the cache into ``out_dir`` and compare it with the original.

    ``config`` supplies only where to look: ``run.out_dir`` for the original run and
    ``llm.cache_dir`` for the answers. Everything that shapes the result comes from the run's own
    snapshot. Replay mode sends nothing: a missing answer is a hard error, not a call.
    """
    original = config.path(config.run.out_dir) / run_id
    if not is_complete(original):
        raise ReleaseError(f"no finished run '{run_id}' under {original.parent}")

    replay = snapshot_config(config, original)
    target = out_dir or Path(tempfile.mkdtemp(prefix="mmlsa-reproduce-"))
    replay.run.out_dir = str(target)
    replay.llm.cache_dir = str(config.path(config.llm.cache_dir))
    replay.llm.mode = "replay"

    result = execute_run(replay, run_id=run_id, progress=progress, allow_code_change=True)
    outcome = Reproduction(run_id=run_id, replay_dir=result.run_dir)
    for name in COMPARED:
        first, second = original / name, result.run_dir / name
        outcome.matches[name] = (
            first.is_file() and second.is_file() and first.read_bytes() == second.read_bytes()
        )
    return outcome


def write_reproduction(outcome: Reproduction) -> Path:
    """Record the comparison beside the replayed run."""
    path = outcome.replay_dir.parent / f"{outcome.run_id}.reproduction.json"
    payload = {"run_id": outcome.run_id, "identical": outcome.identical, "files": outcome.matches}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = [
    "COMPARED",
    "Release",
    "ReleaseError",
    "Reproduction",
    "build_release",
    "reproduce_run",
    "snapshot_config",
    "used_cache_keys",
    "write_reproduction",
]
