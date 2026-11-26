"""Noise robustness: labels hold with and without noise injection (docs/SPEC.md section 7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.validation.conftest import replay_check


def test_noise_robustness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = replay_check("noise", tmp_path, monkeypatch)
    assert result.verdict == "pass", f"{result.measured}; passes if {result.condition}"
