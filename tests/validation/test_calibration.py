"""Calibration: repeated rewrites of the same chunks vary little (docs/SPEC.md section 7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.validation.conftest import replay_check


def test_calibration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = replay_check("calibration", tmp_path, monkeypatch)
    assert result.verdict == "pass", f"{result.measured}; passes if {result.condition}"
