"""Shared fixtures and the global guardrails.

The important thing this file does is make it impossible for a test to reach a real provider by
accident. CI holds no API keys, and a test that quietly needed one would fail there in a way that
looks like a bug in the code rather than a bug in the test.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = REPO_ROOT / "configs"
SRC_DIR = REPO_ROOT / "src" / "mmlsa"

LIVE_ENV_VAR = "MMLSA_ALLOW_LIVE"
"""Set to 1 only when deliberately exercising a real provider by hand. CI never sets it."""


@pytest.fixture(autouse=True)
def _block_live_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove provider credentials from the environment for the duration of every test.

    A concrete provider that reads its key at construction time then fails loudly instead of issuing
    a real, billable request from a test run.
    """
    if os.environ.get(LIVE_ENV_VAR) == "1":
        return
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _isolate_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ``MMLSA_*`` overrides so a developer's shell cannot change what the tests assert."""
    for name in list(os.environ):
        if name.startswith("MMLSA_") and name != LIVE_ENV_VAR:
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def repo_root() -> Path:
    """The repository root."""
    return REPO_ROOT


@pytest.fixture
def configs_dir() -> Path:
    """The directory holding the shipped configuration files."""
    return CONFIGS_DIR
