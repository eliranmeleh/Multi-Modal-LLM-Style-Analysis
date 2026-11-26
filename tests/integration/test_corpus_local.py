"""``corpus fetch`` and ``corpus verify`` on texts supplied locally, in the folders a config selects.

The mini corpus is entirely local (``gutenberg_id: null``), so nothing here touches the network. Its
four sets are copied to temporary folders and the configuration is pointed at them, which is also
the check that both commands follow the configuration rather than the default folders under
``data/``: before, ``fetch`` refused local texts and wrote no manifest, so a corpus of one's own
texts could not be verified at all.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mmlsa.cli import app
from tests.conftest import CONFIGS_DIR, REPO_ROOT

FIXTURES = REPO_ROOT / "tests" / "fixtures"
FOLDERS = {
    "corpus.dir": "mini_corpus",
    "noise.pool_dir": "mini_noise",
    "experiment.heldout.dir": "mini_heldout",
    "experiment.mixture.dir": "mini_mixture",
}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    for folder in FOLDERS.values():
        shutil.copytree(FIXTURES / folder, tmp_path / folder)
    return tmp_path


def invoke(command: str, workspace: Path):
    arguments = ["corpus", command, "--config", str(CONFIGS_DIR / "mini.yaml")]
    options = {key: (workspace / folder).as_posix() for key, folder in FOLDERS.items()}
    options["corpus.manifest"] = (workspace / "manifest.json").as_posix()
    for key, value in options.items():
        arguments += ["--set", f"{key}={value}"]
    return CliRunner().invoke(app, arguments)


def test_fetch_records_local_texts_in_the_manifest(workspace: Path) -> None:
    outcome = invoke("fetch", workspace)

    assert outcome.exit_code == 0, outcome.output
    manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    recorded = {
        name: [entry["id"] for entry in entries] for name, entries in manifest["sets"].items()
    }
    assert recorded == {
        "texts": ["mini_alpha", "mini_beta", "mini_gamma"],
        "noise_pool": ["mini_noise_one"],
        "heldout": ["mini_heldout_kin", "mini_heldout_stranger"],
        "mixture_sources": ["mini_mixture_source"],
    }
    assert outcome.output.count("local ") == 7


def test_fetch_leaves_a_local_text_as_it_is(workspace: Path) -> None:
    before = (workspace / "mini_corpus" / "mini_alpha.txt").read_bytes()
    invoke("fetch", workspace)
    assert (workspace / "mini_corpus" / "mini_alpha.txt").read_bytes() == before


def test_verify_passes_on_the_configured_folders(workspace: Path) -> None:
    invoke("fetch", workspace)
    outcome = invoke("verify", workspace)

    assert outcome.exit_code == 0, outcome.output
    assert "checks passed" in outcome.output


def test_verify_catches_a_changed_local_text(workspace: Path) -> None:
    invoke("fetch", workspace)
    text = workspace / "mini_corpus" / "mini_beta.txt"
    text.write_text(text.read_text(encoding="utf-8") + "\nAn added line.\n", encoding="utf-8")

    outcome = invoke("verify", workspace)

    assert outcome.exit_code == 1
    assert "mini_beta: checksum drift" in outcome.output


def test_fetch_names_a_missing_local_text(workspace: Path) -> None:
    (workspace / "mini_heldout" / "mini_heldout_kin.txt").unlink()

    outcome = invoke("fetch", workspace)

    assert outcome.exit_code == 1
    assert "mini_heldout_kin: supplied locally, but no text at" in outcome.output
    assert not (workspace / "manifest.json").exists()
