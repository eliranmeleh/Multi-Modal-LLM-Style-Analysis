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

corpus_app = typer.Typer(help="Acquire, normalize and verify the corpus.", no_args_is_help=True)
app.add_typer(corpus_app, name="corpus")

cache_app = typer.Typer(help="Inspect the LLM response cache.", no_args_is_help=True)
app.add_typer(cache_app, name="cache")


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


@corpus_app.command("fetch")
def corpus_fetch(
    config: ConfigOption = Path("configs/default.yaml"),
    only: Annotated[
        str | None,
        typer.Option("--only", help="Fetch one set: texts, noise_pool, heldout, mixture_sources."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-download even when a raw copy is already cached.")
    ] = False,
    pause: Annotated[
        float,
        typer.Option("--pause", help="Seconds between requests. Gutenberg is a donated service."),
    ] = 1.0,
) -> None:
    """Download, strip Gutenberg boilerplate, normalize, and write the manifest."""
    from mmlsa.corpus.loader import SET_NAMES, CorpusError, fetch_text, load_sources, write_text
    from mmlsa.corpus.manifest import build_manifest, write_manifest

    resolved = _load(config, None, None, None, None)
    sources = load_sources(resolved.path(resolved.corpus.sources))

    wanted = [only] if only else list(SET_NAMES)
    if only and only not in SET_NAMES:
        typer.secho(
            f"unknown set '{only}'. Known: {', '.join(SET_NAMES)}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=2)

    texts: dict[str, str] = {}
    reports = {}
    failures: list[str] = []

    for set_name in wanted:
        declared = sources.sets.get(set_name, [])
        typer.echo(f"\n{set_name} ({len(declared)} texts)")
        for source in declared:
            try:
                text, report = fetch_text(source, resolved.root, force=force, pause_seconds=pause)
            except CorpusError as exc:
                failures.append(f"{source.id}: {exc}")
                typer.secho(f"  FAIL  {source.id}", fg=typer.colors.RED)
                continue

            write_text(source, resolved.root, text)
            texts[source.id] = text
            reports[source.id] = report
            typer.echo(f"  ok    {source.id:42} {len(text.split()):>7,} words")

    if failures:
        typer.secho(f"\n{len(failures)} texts failed:", fg=typer.colors.RED, err=True)
        for failure in failures:
            typer.secho(f"  {failure}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    manifest = build_manifest(
        sources, resolved.root, texts, reports, function_words_path=resolved.distance.function_words
    )
    path = write_manifest(manifest, resolved.path(resolved.corpus.manifest))
    typer.echo(f"\nmanifest written to {path}")
    typer.echo(
        f"corpus: {manifest['totals']['n_texts']} creations, {manifest['totals']['n_words']:,} words"
    )


@corpus_app.command("verify")
def corpus_verify(
    config: ConfigOption = Path("configs/default.yaml"),
) -> None:
    """Check every text against the manifest: checksums, counts, boilerplate, set disjointness."""
    from mmlsa.corpus.loader import CorpusError, load_sources
    from mmlsa.corpus.manifest import read_manifest, verify

    resolved = _load(config, None, None, None, None)
    try:
        sources = load_sources(resolved.path(resolved.corpus.sources))
        manifest = read_manifest(resolved.path(resolved.corpus.manifest))
    except CorpusError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    result = verify(sources, resolved.root, manifest, expected_count=resolved.corpus.expected_count)

    for warning in result.warnings:
        typer.secho(f"warn  {warning}", fg=typer.colors.YELLOW)
    for failure in result.failures:
        typer.secho(f"FAIL  {failure}", fg=typer.colors.RED)

    if result.ok:
        typer.secho(
            f"\n{result.checks_run} checks passed"
            + (f", {len(result.warnings)} warnings" if result.warnings else ""),
            fg=typer.colors.GREEN,
        )
        return

    typer.secho(
        f"\n{len(result.failures)} of {result.checks_run} checks failed",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(code=1)


@cache_app.command("stats")
def cache_stats(
    config: ConfigOption = Path("configs/default.yaml"),
    set_options: SetOption = None,
) -> None:
    """Report what the response cache holds.

    Worth checking before any wide job: a populated cache is the difference between a run that costs
    an hour and one that costs nothing.
    """
    from mmlsa.llm.cache import ResponseCache

    resolved = _load(config, None, None, None, set_options)
    cache = ResponseCache(resolved.path(resolved.llm.cache_dir))

    entries = cache.count()
    typer.echo(f"directory   {cache.root}")
    typer.echo(f"entries     {entries:,}")
    typer.echo(f"size        {cache.size_bytes() / 1_048_576:.1f} MiB")
    if entries == 0:
        typer.echo("\nThe cache is empty; every call in the next run will be issued live.")


@cache_app.command("verify")
def cache_verify(
    config: ConfigOption = Path("configs/default.yaml"),
    set_options: SetOption = None,
) -> None:
    """Check that every cache entry is readable and addressed by its own contents.

    An entry whose stored key does not match its filename would be served for the wrong request,
    which is the one cache failure that produces plausible wrong numbers rather than an error.
    """
    import json

    from mmlsa.llm.cache import ResponseCache

    resolved = _load(config, None, None, None, set_options)
    cache = ResponseCache(resolved.path(resolved.llm.cache_dir))

    if not cache.root.is_dir():
        typer.echo(f"no cache at {cache.root}")
        return

    checked = 0
    problems: list[str] = []
    for path in sorted(cache.root.rglob("*.json")):
        checked += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name}: unreadable ({exc})")
            continue
        if payload.get("key") != path.stem:
            problems.append(f"{path.name}: stored key does not match the filename")
        if "response" not in payload:
            problems.append(f"{path.name}: no response recorded")

    for problem in problems:
        typer.secho(f"FAIL  {problem}", fg=typer.colors.RED)

    if problems:
        typer.secho(f"\n{len(problems)} of {checked} entries failed", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho(f"{checked} cache entries verified", fg=typer.colors.GREEN)


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
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Continue a specific run directory instead of starting one."),
    ] = None,
    verbose: VerboseOption = False,
) -> None:
    """Execute the pipeline. Run with --dry-run first before any wide job."""
    from mmlsa.corpus.loader import CorpusError
    from mmlsa.pipeline.noise import NoiseError
    from mmlsa.pipeline.orchestrator import RunError, execute_run, plan_run

    configure_logging(verbose=verbose)
    resolved = _load(config, provider, mode, seed, set_options)

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

    try:
        plan = plan_run(resolved, run_id=run_id or "")
    except (CorpusError, NoiseError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.echo("")
    typer.echo(f"creations       {plan.n_creations}")
    typer.echo(f"chunks          {plan.n_chunks:,}  (per run)")
    typer.echo(f"noise injected  {', '.join(plan.noise_creations) or 'none'}")
    typer.echo(f"profile calls   {plan.profile_calls:,}")
    typer.echo(f"rewrite calls   {plan.rewrite_calls:,}")
    typer.secho(f"TOTAL CALLS     {plan.total_calls:,}", bold=True)
    typer.echo(f"input tokens    ~{plan.estimated_input_tokens:,} (estimated)")

    if dry_run:
        typer.echo("\nDry run: nothing was requested and nothing was written.")
        return

    try:
        result = execute_run(resolved, run_id=run_id or "")
    except (RunError, CorpusError, NoiseError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.echo("")
    typer.secho(f"run {result.run_id}", bold=True)
    typer.echo(f"artifacts       {result.run_dir}")
    typer.echo(f"tau             {result.threshold.tau:.4f} ({result.threshold.method})")
    typer.echo(
        f"suspicious      {len(result.classification.suspicious)} of "
        f"{len(result.classification.labels)}"
    )
    for creation_id in sorted(result.classification.suspicious):
        typer.echo(f"                  {creation_id}")
    if result.classification.borderline:
        typer.echo(f"borderline      {', '.join(sorted(result.classification.borderline))}")
    if result.threshold.flagged:
        typer.secho(
            "\nThe threshold is flagged. Inspect figures/histogram.png and threshold.json "
            "before reporting these labels.",
            fg=typer.colors.YELLOW,
        )


if __name__ == "__main__":
    app()
