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
    for command in ("version", "run", "config"):
        assert command in result.stdout


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


def test_dry_run_resolves_and_prints_the_plan() -> None:
    """M1 acceptance: resolves and prints without touching data."""
    result = runner.invoke(app, ["run", "--config", str(CONFIGS_DIR / "poc.yaml"), "--dry-run"])

    assert result.exit_code == 0
    assert "config_hash" in result.stdout
    assert "chunk length P  400" in result.stdout
    assert "runs (M)        3" in result.stdout


def test_a_real_run_refuses_until_the_orchestrator_exists() -> None:
    """Better an explicit refusal naming the milestone than a partial run that looks complete."""
    result = runner.invoke(app, ["run", "--config", str(CONFIGS_DIR / "mini.yaml")])

    assert result.exit_code == 3


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
