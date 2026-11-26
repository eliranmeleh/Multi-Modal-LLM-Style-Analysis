"""Held-out generalization: reserved texts are classified as expected (docs/SPEC.md section 7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.validation.conftest import replay_check


def test_heldout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = replay_check("heldout", tmp_path, monkeypatch)
    assert result.verdict == "pass", f"{result.measured}; passes if {result.condition}"
