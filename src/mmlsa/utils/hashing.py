"""Deterministic hashing helpers.

Every hash in this project is a sha256 over *canonical* JSON: sorted keys, no insignificant
whitespace, UTF-8. Canonical form is what makes a hash a stable identity rather than an accident of
dictionary ordering, which matters for the config hash in the run id and for the LLM cache key.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(payload: Any) -> str:
    """Serialize to JSON in a form that is byte-identical for equal values."""
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def hash_payload(payload: Any) -> str:
    """Return the sha256 hex digest of ``payload`` in canonical JSON form."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def hash_text(text: str) -> str:
    """Return the sha256 hex digest of a string, UTF-8 encoded."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_file(path: str) -> str:
    """Return the sha256 hex digest of a file's bytes, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:  # noqa: PTH123 - binary streaming read
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()
