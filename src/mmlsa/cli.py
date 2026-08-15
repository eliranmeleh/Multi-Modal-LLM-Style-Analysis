"""The command-line surface. This is the only module permitted to print.

The full target command set is specified in ``docs/ARCHITECTURE.md`` section 8. Commands are
registered here as the milestone that implements them lands, so ``--help`` never advertises
something that does not work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml

from mmlsa import __version__
from mmlsa.config import Config, ConfigError
from mmlsa.settings import build_config
from mmlsa.utils.logging import configure_logging

app = typer.Typer(
    name="mmlsa",
    help="Detect misattributed creations in a literary corpus through LLM-based style normalization.",
    no_args_is_help=True,
    add_completion=False,
)

config_app = typer.Typer(help="Inspect and validate configuration files.", no_args_is_help=True)
app.add_typer(config_app, name="config")


ConfigOption = Annotated[
    Path, typer.Option("--config", "-c", help="Path to a configuration file under configs/.")
]
ProviderOption = Annotated[
    str | None, typer.Option("--provider", help="Override llm.provider for this invocation.")
]
ModeOption = Annotated[
    str | None, typer.Option("--mode", help="Override llm.mode: live, replay or refresh.")
]
SeedOption = Annotated[int | None, typer.Option("--seed", help="Override run.seed.")]
SetOption = Annotated[
    list[str] | None,
    typer.Option("--set", help="Override any key: --set chunking.P=200. Repeatable."),
]
VerboseOption = Annotated[bool, typer.Option("--verbose", "-v", help="Debug-level logging.")]


@app.callback()
def main() -> None:
    """Root command group. See the subcommands below."""


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


def _load(
    config: Path,
    provider: str | None,
    mode: str | None,
    seed: int | None,
    set_options: list[str] | None,
) -> Config:
    """Resolve a configuration, turning any configuration error into a clean CLI exit."""
    try:
        return build_config(
            config, provider=provider, mode=mode, seed=seed, set_options=set_options
        )
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc


@config_app.command("show")
def config_show(
    config: ConfigOption,
    provider: ProviderOption = None,
    mode: ModeOption = None,
    seed: SeedOption = None,
    set_options: SetOption = None,
) -> None:
    """Print the fully resolved configuration and its hash, without touching any data."""
    resolved = _load(config, provider, mode, seed, set_options)
    typer.echo(
        yaml.safe_dump(resolved.to_dict(), sort_keys=True, default_flow_style=False).rstrip()
    )
    typer.echo(f"\n# config_hash: {resolved.config_hash()}")
    typer.echo(f"# project_root: {resolved.root}")


@config_app.command("validate")
def config_validate(
    directory: Annotated[
        Path, typer.Option("--dir", help="Directory of configuration files to validate.")
    ] = Path("configs"),
) -> None:
    """Resolve and validate every configuration file in a directory.

    This is the check that catches a key added to a child config but never declared in the model.
    """
    files = sorted(directory.glob("*.yaml"))
    if not files:
        typer.secho(f"no configuration files found in {directory}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    failures = 0
    for path in files:
        try:
            resolved = build_config(path)
        except ConfigError as exc:
            failures += 1
            typer.secho(f"FAIL  {path.name}", fg=typer.colors.RED)
            typer.secho(f"      {exc}", fg=typer.colors.RED)
        else:
            typer.secho(f"ok    {path.name}  {resolved.config_hash()[:12]}", fg=typer.colors.GREEN)

    if failures:
        typer.secho(
            f"\n{failures} of {len(files)} configurations failed", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1)
    typer.echo(f"\n{len(files)} configurations resolved and validated")


@app.command()
def run(
    config: ConfigOption,
    provider: ProviderOption = None,
    mode: ModeOption = None,
    seed: SeedOption = None,
    set_options: SetOption = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Resolve and plan only. Issues no request and writes nothing."
        ),
    ] = False,
    verbose: VerboseOption = False,
) -> None:
    """Execute the pipeline. Run with --dry-run first before any wide job."""
    configure_logging(verbose=verbose)
    resolved = _load(config, provider, mode, seed, set_options)

    if not dry_run:
        typer.secho(
            "Pipeline execution is not implemented yet; it lands at milestone M8.\n"
            "Use --dry-run to resolve and inspect the plan.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=3)

    typer.echo(f"config          {config}")
    typer.echo(f"config_hash     {resolved.config_hash()}")
    typer.echo(f"provider        {resolved.llm.provider}  (mode: {resolved.llm.mode})")
    typer.echo(f"runs (M)        {resolved.run.M}")
    typer.echo(f"seed            {resolved.run.seed}")
    typer.echo(f"chunk length P  {resolved.chunking.P}")
    typer.echo(f"distance        {resolved.distance.metric}")
    typer.echo(f"classifier      {resolved.classify.method}")
    subset = resolved.corpus.include_ids
    typer.echo(f"corpus subset   {'whole corpus' if subset is None else ', '.join(subset)}")
    typer.echo(
        "\nCall estimation over the real corpus is added with corpus loading at milestone M2."
    )


if __name__ == "__main__":
    app()
