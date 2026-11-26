"""Replaying a recorded validation check: ``pytest tests/validation -q`` (milestone M14).

Each check is re-run in ``replay`` mode against a **recorded bundle**, a directory under
``tests/fixtures/recorded_runs/<check>/`` holding:

* ``recording.yaml``: the config file and ``--set`` options the runs used, and the run id(s) the
  check reads (``baseline``, or ``with_noise`` and ``without_noise``);
* ``runs/<run id>/``: those finished run directories, copied as they are;
* ``cache/``: the saved answers of the baseline and of the check (``docs/RUNBOOK.md``).

Nothing is called: a missing answer is a cache miss, which fails the test. Until a check has been
recorded, its test is skipped with a message saying so, rather than passing on nothing.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from mmlsa.experiments import validation
from mmlsa.settings import build_config
from tests.conftest import REPO_ROOT

RECORDED = REPO_ROOT / "tests" / "fixtures" / "recorded_runs"

LIVE_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
"""A live provider reads its key when it is built. In replay mode it never sends a request, so a
placeholder lets it be built on a machine, such as CI, that holds no key."""


def replay_check(check: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Re-run one recorded check in replay mode and return its result, or skip if unrecorded."""
    bundle = RECORDED / check
    recording_file = bundle / "recording.yaml"
    if not recording_file.is_file():
        pytest.skip(
            f"no recorded {check} check yet: record one against a run of record and copy it to "
            f"{bundle.relative_to(REPO_ROOT).as_posix()}/ (docs/RUNBOOK.md, validation checks)"
        )
    recording = yaml.safe_load(recording_file.read_text(encoding="utf-8"))

    runs = tmp_path / "runs"
    shutil.copytree(bundle / "runs", runs)
    config = build_config(
        REPO_ROOT / recording["config"],
        set_options=[
            *recording.get("set", []),
            f"run.out_dir={runs.as_posix()}",
            f"llm.cache_dir={(bundle / 'cache').as_posix()}",
            "llm.mode=replay",
        ],
    )
    if config.llm.provider in LIVE_KEYS:
        monkeypatch.setenv(LIVE_KEYS[config.llm.provider], "replay-sends-no-request")

    if check == "noise":
        result = validation.run_noise(config, recording["with_noise"], recording["without_noise"])
    else:
        runner = {
            "calibration": validation.run_calibration,
            "mixture": validation.run_mixture,
            "heldout": validation.run_heldout,
        }[check]
        result = runner(config, recording["baseline"], progress=False)

    print(f"\n{check}: measured {result.measured}; passes if {result.condition}")
    return result
