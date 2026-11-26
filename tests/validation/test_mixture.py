"""Synthetic mixture: spliced passages are flagged and located (docs/SPEC.md section 7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.validation.conftest import replay_check


def test_mixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = replay_check("mixture", tmp_path, monkeypatch)
    assert result.verdict == "pass", f"{result.measured}; passes if {result.condition}"
