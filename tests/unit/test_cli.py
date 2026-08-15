"""The command-line surface.

M0 and M1 acceptance: the help lists the commands, and a dry run resolves a configuration and prints
it without touching data or issuing a request.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from mmlsa import __version__
from mmlsa.cli import app
from tests.conftest import CONFIGS_DIR

runner = CliRunner()


def test_help_lists_the_registered_commands() -> None:
    """``python -m mmlsa --help`` prints the command list."""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("version", "run", "config", "corpus", "cache"):
        assert command in result.stdout


def test_cache_stats_reports_an_empty_cache(tmp_path: Path) -> None:
    """Run before any wide job: an empty cache means every call will be issued live."""
    result = runner.invoke(
        app,
        [
            "cache",
            "stats",
            "--config",
            str(CONFIGS_DIR / "mini.yaml"),
            "--set",
            f"llm.cache_dir={(tmp_path / 'cache').as_posix()}",
        ],
    )

    assert result.exit_code == 0
    assert "entries     0" in result.stdout
    assert "empty" in result.stdout


def test_cache_verify_detects_an_entry_whose_key_does_not_match_its_filename(
    tmp_path: Path,
) -> None:
    """The one cache failure that yields plausible wrong numbers instead of an error."""
    import json

    shard = tmp_path / "cache" / "ab"
    shard.mkdir(parents=True)
    (shard / f"{'ab' * 32}.json").write_text(
        json.dumps({"key": "a-different-key", "response": {"text": "x"}}), encoding="utf-8"
    )

    result = runner.invoke(
        app,
        [
            "cache",
            "verify",
            "--config",
            str(CONFIGS_DIR / "mini.yaml"),
            "--set",
            f"llm.cache_dir={(tmp_path / 'cache').as_posix()}",
        ],
    )

    assert result.exit_code == 1
    assert "does not match the filename" in result.stdout


def test_version_prints_the_package_version() -> None:
    """A trivial command, but it proves the entry point is wired to the package."""
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_config_show_prints_a_resolvable_flattened_config() -> None:
    """The printed document must be loadable on its own, with no parent file present."""
    result = runner.invoke(app, ["config", "show", "--config", str(CONFIGS_DIR / "poc.yaml")])

    assert result.exit_code == 0
    assert "config_hash:" in result.stdout

    body = result.stdout.split("# config_hash:")[0]
    parsed = yaml.safe_load(body)
    assert "extends" not in parsed
    assert parsed["chunking"]["P"] == 400


def test_config_show_applies_cli_overrides() -> None:
    """Precedence is visible from the CLI, not only from the loader's unit tests."""
    result = runner.invoke(
        app,
        [
            "config",
            "show",
            "--config",
            str(CONFIGS_DIR / "poc.yaml"),
            "--provider",
            "fake",
            "--set",
            "chunking.P=250",
        ],
    )

    parsed = yaml.safe_load(result.stdout.split("# config_hash:")[0])
    assert result.exit_code == 0
    assert parsed["llm"]["provider"] == "fake"
    assert parsed["chunking"]["P"] == 250


def test_config_validate_accepts_every_shipped_config() -> None:
    """The check that a key added to a child config was also declared in the model."""
    result = runner.invoke(app, ["config", "validate", "--dir", str(CONFIGS_DIR)])

    assert result.exit_code == 0
    assert "configurations resolved and validated" in result.stdout


def test_config_validate_reports_a_broken_config(tmp_path: Path) -> None:
    """A directory holding one bad file must fail, and name the file."""
    (tmp_path / "good.yaml").write_text("chunking:\n  P: 200\n", encoding="utf-8")
    (tmp_path / "bad.yaml").write_text("chunking:\n  PP: 200\n", encoding="utf-8")

    result = runner.invoke(app, ["config", "validate", "--dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "FAIL  bad.yaml" in result.stdout


def test_config_validate_on_an_empty_directory_is_an_error(tmp_path: Path) -> None:
    """Validating nothing must not look like validating everything successfully."""
    result = runner.invoke(app, ["config", "validate", "--dir", str(tmp_path)])

    assert result.exit_code == 2


def test_dry_run_reports_the_plan_without_writing_anything(tmp_path: Path) -> None:
    """Run this before any wide job. It must report the real call count and touch nothing."""
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(CONFIGS_DIR / "poc.yaml"),
            "--dry-run",
            "--set",
            f"run.out_dir={(tmp_path / 'runs').as_posix()}",
        ],
    )

    assert result.exit_code == 0
    assert "chunk length P  400" in result.stdout
    assert "runs (M)        3" in result.stdout
    assert "TOTAL CALLS" in result.stdout
    assert "nothing was requested" in result.stdout
    assert not (tmp_path / "runs").exists()


def test_the_dry_run_names_the_model_it_planned_for() -> None:
    """M9 compares models, and a plan that names only the provider hides which one it priced."""
    result = runner.invoke(
        app, ["run", "--config", str(CONFIGS_DIR / "poc.yaml"), "--dry-run", "--provider", "fake"]
    )

    assert result.exit_code == 0
    assert "model           fake-1" in result.stdout


def test_the_dry_run_plans_against_the_configured_model_context_window() -> None:
    """The profile-call count depends on the window, and the window depends on the model.

    A model with an eighth of the context needs several times as many extraction calls. Reporting
    the same figure for both would understate the cost of the smaller model before it is chosen.
    """
    arguments = ["run", "--config", str(CONFIGS_DIR / "full.yaml"), "--dry-run", "--provider"]

    wide = runner.invoke(app, [*arguments, "gemini"])
    narrow = runner.invoke(app, [*arguments, "openai", "--set", "llm.model_id=gpt-4o"])

    def profile_calls(output: str) -> int:
        line = next(line for line in output.splitlines() if line.startswith("profile calls"))
        return int(line.split()[-1].replace(",", ""))

    assert (wide.exit_code, narrow.exit_code) == (0, 0)
    assert profile_calls(narrow.stdout) > profile_calls(wide.stdout)


def test_a_key_in_a_dotenv_file_reaches_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``README.md`` tells a new contributor to put their key in ``.env``. Nothing read it.

    Without this the first live call fails with "no API key" while the key sits in the file the
    documentation named. The environment is sandboxed here so a fake key cannot escape the test.
    """
    import os

    monkeypatch.setattr(os, "environ", dict(os.environ))
    os.environ.pop("GEMINI_API_KEY", None)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-the-dotenv-file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert os.environ["GEMINI_API_KEY"] == "from-the-dotenv-file"


def test_an_exported_key_wins_over_the_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise a stale file would silently override the key a developer just exported."""
    import os

    monkeypatch.setattr(os, "environ", dict(os.environ))
    os.environ["GEMINI_API_KEY"] = "from-the-shell"
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-the-dotenv-file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    runner.invoke(app, ["version"])

    assert os.environ["GEMINI_API_KEY"] == "from-the-shell"


def test_the_proof_of_concept_subset_names_creations_that_exist() -> None:
    """A subset naming a creation that is not in the corpus is refused, not silently shrunk.

    `configs/poc.yaml` was written before the corpus was assembled and named five identifiers that
    never existed. Without this check the proof of concept would have run on nothing.
    """
    result = runner.invoke(app, ["run", "--config", str(CONFIGS_DIR / "poc.yaml"), "--dry-run"])

    assert result.exit_code == 0
    assert "creations       5" in result.stdout


def test_a_subset_naming_an_unknown_creation_is_refused(tmp_path: Path) -> None:
    """The guard that caught the above."""
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(CONFIGS_DIR / "poc.yaml"),
            "--dry-run",
            "--set",
            "corpus.include_ids=[not_a_creation]",
        ],
    )

    assert result.exit_code == 2
    assert "not in the corpus" in result.stdout + str(result.stderr or "")


def test_a_real_run_produces_a_run_directory(tmp_path: Path) -> None:
    """The M8 acceptance criterion, through the command a user would actually type."""
    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(CONFIGS_DIR / "mini.yaml"),
            "--provider",
            "fake",
            "--set",
            f"run.out_dir={(tmp_path / 'runs').as_posix()}",
            "--set",
            f"llm.cache_dir={(tmp_path / 'cache').as_posix()}",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "tau" in result.stdout

    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "scores.csv").is_file()
    assert (runs[0] / "manifest.json").is_file()


@pytest.mark.parametrize(
    "arguments",
    [
        ["config", "show", "--config", "configs/does_not_exist.yaml"],
        ["config", "show", "--config", "configs/poc.yaml", "--set", "chunking.PP=1"],
        ["config", "show", "--config", "configs/poc.yaml", "--provider", "not_a_provider"],
    ],
)
def test_configuration_errors_exit_cleanly(arguments: list[str]) -> None:
    """A bad configuration is a clean exit with a message, never a traceback."""
    result = runner.invoke(app, arguments)

    assert result.exit_code == 2
    assert result.exception is None or isinstance(result.exception, SystemExit)
