"""The command-line surface. This is the only module permitted to print.

The full target command set is specified in ``docs/ARCHITECTURE.md`` section 8. Commands are
registered here as the milestone that implements them lands, so ``--help`` never advertises
something that does not work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from dotenv import find_dotenv, load_dotenv

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

experiment_app = typer.Typer(help="Run the validation experiments.", no_args_is_help=True)
app.add_typer(experiment_app, name="experiment")


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
    """Root command group. See the subcommands below.

    Loads ``.env`` into the environment first, since that is where ``README.md`` tells a new
    contributor to put their API key. Existing environment variables win, so an exported key
    overrides the file rather than the other way round, and nothing here reads or echoes a value
    (R6).

    The search starts at the working directory rather than at this file, which is the difference
    between finding the ``.env`` the user just created and finding the one next to the installed
    package.
    """
    found = find_dotenv(usecwd=True)
    if found:
        load_dotenv(found, override=False)


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
    allow_code_change: Annotated[
        bool,
        typer.Option(
            "--allow-code-change",
            help="Continue a run under code other than the code it started with.",
        ),
    ] = False,
    verbose: VerboseOption = False,
) -> None:
    """Execute the pipeline. Run with --dry-run first before any wide job."""
    from mmlsa.corpus.loader import CorpusError
    from mmlsa.llm.providers import default_model
    from mmlsa.pipeline.noise import NoiseError
    from mmlsa.pipeline.orchestrator import RunError, execute_run, plan_run

    configure_logging(verbose=verbose)
    resolved = _load(config, provider, mode, seed, set_options)

    typer.echo(f"config          {config}")
    typer.echo(f"config_hash     {resolved.config_hash()}")
    typer.echo(f"provider        {resolved.llm.provider}  (mode: {resolved.llm.mode})")
    model = (
        resolved.llm.model_id
        or default_model(resolved.llm.provider)
        or "the provider's own default"
    )
    typer.echo(f"model           {model}")
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
    if plan.cache_checked:
        typer.echo(f"already saved   {plan.cached_calls:,}  (in {resolved.llm.cache_dir}, no cost)")
        typer.secho(f"new calls       {plan.calls_to_issue:,}", bold=True)
    else:
        typer.echo("already saved   not checked: the model cannot be named offline")
    typer.echo(f"input tokens    ~{plan.estimated_input_tokens:,} (estimated, for every call)")

    if dry_run:
        typer.echo("\nDry run: nothing was requested and nothing was written.")
        return

    try:
        result = execute_run(resolved, run_id=run_id or "", allow_code_change=allow_code_change)
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


@app.command()
def compare(
    config: ConfigOption,
    models: Annotated[
        list[str] | None,
        typer.Option(
            "--model",
            "-m",
            help="A candidate as provider[:model_id], e.g. gemini:gemini-2.5-flash. Repeatable.",
        ),
    ] = None,
    chunks: Annotated[
        int, typer.Option("--chunks", help="How many identical chunks each candidate rewrites.")
    ] = 10,
    out_dir: Annotated[
        Path | None,
        typer.Option(
            "--out-dir", help="Where to write the comparison. Defaults under run.out_dir."
        ),
    ] = None,
    seed: SeedOption = None,
    set_options: SetOption = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the confirmation and issue the calls.")
    ] = False,
    verbose: VerboseOption = False,
) -> None:
    """Compare candidate models on identical chunks (M9).

    Prints the plan and stops, unless --yes. Profile extraction sends the whole configured corpus to
    every candidate, so point this at a small subset before pointing it at the corpus.
    """
    from datetime import UTC, datetime

    from mmlsa.corpus.loader import CorpusError
    from mmlsa.pipeline.compare import (
        Candidate,
        ComparisonError,
        compare_models,
        plan_comparison,
    )

    configure_logging(verbose=verbose)
    resolved = _load(config, None, None, seed, set_options)

    try:
        candidates = [Candidate.parse(specification) for specification in models or []]
        if not candidates:
            candidates = [Candidate(resolved.llm.provider, resolved.llm.model_id)]
        plan = plan_comparison(resolved, candidates, size=chunks)
    except (ComparisonError, CorpusError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"config          {config}")
    typer.echo(f"seed            {resolved.run.seed}")
    typer.echo(f"chunks          {plan.n_chunks} identical passages per candidate")
    typer.echo("")
    for label, resolved_model, profile_calls in plan.candidates:
        typer.echo(f"  {label:<28} {resolved_model:<28} {profile_calls} profile call(s)")
    typer.echo("")
    typer.secho(f"TOTAL CALLS     {plan.total_calls:,}", bold=True)
    typer.echo(f"input tokens    ~{plan.estimated_input_tokens:,} (estimated)")

    if not yes:
        typer.echo("\nNothing was requested. Re-run with --yes to issue these calls.")
        return

    directory = out_dir or (
        resolved.path(resolved.run.out_dir)
        / f"compare-{datetime.now(UTC).strftime('%Y%m%dT%H%M')}-s{resolved.run.seed}"
    )

    try:
        result = compare_models(resolved, candidates, directory, size=chunks)
    except (ComparisonError, CorpusError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.echo("")
    typer.secho(f"artifacts       {directory}", bold=True)
    for summary in result.table():
        if summary["error"]:
            typer.secho(f"  {summary['model']:<28} {summary['error']}", fg=typer.colors.YELLOW)
        else:
            typer.echo(
                f"  {summary['model']:<28} delta {summary['mean_delta']:.4f} "
                f"(sd {summary['sd_delta']:.4f})  {summary['n_ok']}/{summary['n_chunks']} usable  "
                f"{summary['median_latency_ms']} ms"
            )
    typer.echo("\nRead summary.md, then read rewrites/ by hand. No table answers whether the model")
    typer.echo("is quietly modernizing spelling (docs/TESTING.md section 7).")


RunIdOption = Annotated[
    str, typer.Option("--run-id", "-r", help="A finished run under run.out_dir.")
]


@app.command()
def report(
    run_id: RunIdOption,
    config: ConfigOption = Path("configs/default.yaml"),
    include: Annotated[
        list[str] | None,
        typer.Option(
            "--include", help="A finished experiment run to summarise in the report. Repeatable."
        ),
    ] = None,
    out_dir: Annotated[
        Path | None, typer.Option("--out", help="Where to write. Defaults to reports/<run_id>/.")
    ] = None,
    set_options: SetOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Write the final report of a finished run (M15). Sends no request.

    --config says where to look (run.out_dir) and what to judge against (report.consensus_cases,
    report.compare_to_prior); the run's own settings come from its snapshot.
    """
    from mmlsa.experiments.sensitivity import SensitivityError
    from mmlsa.reporting.report import ReportError, build_report

    configure_logging(verbose=verbose)
    resolved = _load(config, None, None, None, set_options)
    try:
        built = build_report(resolved, run_id, out_dir=out_dir, include=include or [])
    except (ReportError, SensitivityError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.secho(f"report          {built.out_dir / 'report.md'}", bold=True)
    typer.echo(f"stability       {built.stability_verdict} (success metric 1)")
    typer.echo(
        f"consensus       {built.consensus.verdict}: {built.consensus.n_correct} of "
        f"{built.consensus.n_cases}, at least {built.consensus.min_correct} required "
        "(success metric 3)"
    )
    note = "" if built.prior.complete else " (prior list incomplete)"
    typer.echo(f"prior study     {built.prior.counts}{note}")
    for line in built.experiments:
        typer.echo(f"{line['experiment']:<15} {line['verdict']}  {line['run_id']}")


@app.command()
def release(
    run_ids: Annotated[
        list[str], typer.Option("--run-id", "-r", help="A finished run to pack. Repeatable.")
    ],
    config: ConfigOption = Path("configs/default.yaml"),
    name: Annotated[
        str, typer.Option("--name", help="Archive name. Defaults to the first run id.")
    ] = "",
    out_dir: Annotated[
        Path | None, typer.Option("--out", help="Where to write. Defaults to release/.")
    ] = None,
    set_options: SetOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Pack finished runs with exactly the cached answers they used (M15). Sends no request."""
    from mmlsa.reporting.release import ReleaseError, build_release

    configure_logging(verbose=verbose)
    resolved = _load(config, None, None, None, set_options)
    try:
        packed = build_release(resolved, run_ids, out_dir=out_dir, name=name)
    except ReleaseError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.secho(f"archive         {packed.archive}", bold=True)
    typer.echo(f"runs            {', '.join(packed.run_ids)}")
    typer.echo(f"cache entries   {packed.n_cache_entries:,}")
    typer.echo(f"sha256          {packed.sha256}")
    typer.echo("\nAttach the archive and its .sha256 to a GitHub release; never commit it.")


@app.command()
def reproduce(
    run_id: RunIdOption,
    config: ConfigOption = Path("configs/default.yaml"),
    out_dir: Annotated[
        Path | None,
        typer.Option("--out", help="Where to write the replayed run. Defaults to a temp folder."),
    ] = None,
    set_options: SetOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Replay a finished run from the cache and compare it byte for byte (M15's acceptance test).

    Replay mode sends nothing and needs no key: an answer missing from the cache is an error.
    """
    from mmlsa.corpus.loader import CorpusError
    from mmlsa.pipeline.noise import NoiseError
    from mmlsa.pipeline.orchestrator import RunError
    from mmlsa.reporting.release import ReleaseError, reproduce_run, write_reproduction

    configure_logging(verbose=verbose)
    resolved = _load(config, None, None, None, set_options)
    try:
        outcome = reproduce_run(resolved, run_id, out_dir=out_dir, progress=not verbose)
    except (ReleaseError, RunError, CorpusError, NoiseError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    record = write_reproduction(outcome)

    typer.echo(f"replayed run    {outcome.replay_dir}")
    for name, same in outcome.matches.items():
        typer.echo(f"  {name:<16} {'identical' if same else 'DIFFERENT'}")
    typer.echo(f"record          {record}")
    if outcome.identical:
        typer.secho("REPRODUCED      byte for byte", fg=typer.colors.GREEN, bold=True)
    else:
        typer.secho("NOT REPRODUCED", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=1)


@experiment_app.command("control")
def experiment_control(
    config: ConfigOption,
    provider: ProviderOption = None,
    mode: ModeOption = None,
    seed: SeedOption = None,
    set_options: SetOption = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the confirmation and issue the calls.")
    ] = False,
    verbose: VerboseOption = False,
) -> None:
    """Stage 5: Mode A (profile) against Mode B (generic prompt), paired by chunk (M13).

    Prints the plan and stops, unless --yes. Step 1 sends the whole configured corpus once, and each
    sampled chunk is rewritten twice.
    """
    from mmlsa.corpus.loader import CorpusError
    from mmlsa.experiments.control import ControlError, plan_control, run_control
    from mmlsa.pipeline.orchestrator import RunError

    configure_logging(verbose=verbose)
    resolved = _load(config, provider, mode, seed, set_options)
    control = resolved.experiment.control

    try:
        plan = plan_control(resolved)
    except (ControlError, CorpusError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"config          {config}")
    typer.echo(f"provider        {resolved.llm.provider}  (mode: {resolved.llm.mode})")
    typer.echo(f"model           {plan.model}")
    typer.echo(f"seed            {resolved.run.seed}")
    typer.echo(f"creations       {plan.n_creations}")
    typer.echo(
        f"sample          {plan.n_sample:,} of {plan.n_chunks_total:,} chunks"
        f"  ({'stratified' if control.stratify else 'flat'})"
    )
    typer.echo(f"Mode B author   {plan.author_label}")
    typer.echo(f"test            paired t, {control.alternative}, alpha {control.alpha}")
    typer.echo(f"profile calls   {plan.profile_calls:,}")
    typer.echo(f"rewrite calls   {plan.rewrite_calls:,}  (both arms, before any retry)")
    typer.secho(f"TOTAL CALLS     {plan.total_calls:,}", bold=True)
    typer.echo(f"input tokens    ~{plan.estimated_input_tokens:,} (estimated)")

    if not yes:
        typer.echo("\nNothing was requested. Re-run with --yes to issue these calls.")
        return

    try:
        result = run_control(resolved)
    except (ControlError, RunError, CorpusError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    figures = result.statistics
    typer.echo("")
    typer.secho(f"run {result.run_id}", bold=True)
    typer.echo(f"artifacts       {result.run_dir}")
    typer.echo(f"pairs           {figures.n} of {len(result.sample)}")
    if figures.mean_difference is not None:
        typer.echo(f"mean A - B      {figures.mean_difference:+.4f}")
    typer.secho(f"verdict         {figures.verdict}: {figures.reason}", bold=True)
    typer.echo("\nRead summary.md, and the two arms side by side in rewrites/.")


BaselineOption = Annotated[
    str,
    typer.Option("--baseline", "-b", help="The finished run of record the check measures against."),
]
YesOption = Annotated[
    bool, typer.Option("--yes", "-y", help="Skip the confirmation and issue the calls.")
]


def _report_check(result: Any) -> None:
    """Print a validation check's measured value next to its condition, and the verdict."""
    typer.echo("")
    typer.secho(f"run {result.run_id}", bold=True)
    typer.echo(f"artifacts       {result.run_dir}")
    typer.echo(f"measured        {result.measured}")
    typer.echo(f"passes if       {result.condition}")
    typer.secho(f"verdict         {result.verdict}: {result.reason}", bold=True)


def _run_check(
    check: str,
    config: Path,
    baseline: str,
    provider: str | None,
    mode: str | None,
    set_options: list[str] | None,
    yes: bool,
    verbose: bool,
) -> None:
    """Plan a validation check that calls the model, and run it only with --yes."""
    from mmlsa.corpus.loader import CorpusError
    from mmlsa.experiments import validation
    from mmlsa.pipeline.orchestrator import RunError

    configure_logging(verbose=verbose)
    resolved = _load(config, provider, mode, None, set_options)
    try:
        plan = validation.plan_check(resolved, check, baseline)
    except (validation.CheckError, CorpusError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"check           {check}")
    typer.echo(f"config          {config}")
    typer.echo(f"baseline        {baseline}")
    typer.echo(f"provider        {resolved.llm.provider}  (mode: {resolved.llm.mode})")
    typer.echo(f"texts           {plan.n_texts}")
    typer.echo(f"chunks          {plan.n_chunks:,}")
    typer.secho(f"REWRITE CALLS   at most {plan.rewrite_calls:,}  (before any retry)", bold=True)
    typer.echo("                calls the baseline already made come from the cache")

    if not yes:
        typer.echo("\nNothing was requested. Re-run with --yes to issue these calls.")
        return

    runners = {
        "calibration": validation.run_calibration,
        "mixture": validation.run_mixture,
        "heldout": validation.run_heldout,
    }
    try:
        result = runners[check](resolved, baseline)
    except (validation.CheckError, RunError, CorpusError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    _report_check(result)


@experiment_app.command("calibration")
def experiment_calibration(
    config: ConfigOption,
    baseline: BaselineOption,
    provider: ProviderOption = None,
    mode: ModeOption = None,
    set_options: SetOption = None,
    yes: YesOption = False,
    verbose: VerboseOption = False,
) -> None:
    """Validation check 1: repeat rewrites of a chunk sample and measure their spread (M14)."""
    _run_check("calibration", config, baseline, provider, mode, set_options, yes, verbose)


@experiment_app.command("mixture")
def experiment_mixture(
    config: ConfigOption,
    baseline: BaselineOption,
    provider: ProviderOption = None,
    mode: ModeOption = None,
    set_options: SetOption = None,
    yes: YesOption = False,
    verbose: VerboseOption = False,
) -> None:
    """Validation check 2: splice foreign passages into authentic creations and find them (M14)."""
    _run_check("mixture", config, baseline, provider, mode, set_options, yes, verbose)


@experiment_app.command("heldout")
def experiment_heldout(
    config: ConfigOption,
    baseline: BaselineOption,
    provider: ProviderOption = None,
    mode: ModeOption = None,
    set_options: SetOption = None,
    yes: YesOption = False,
    verbose: VerboseOption = False,
) -> None:
    """Validation check 3: classify the reserved held-out texts (M14)."""
    _run_check("heldout", config, baseline, provider, mode, set_options, yes, verbose)


@experiment_app.command("sensitivity")
def experiment_sensitivity(
    config: ConfigOption,
    sweep_id: Annotated[
        str,
        typer.Option("--sweep-id", help="Continue this sweep instead of starting a new one."),
    ] = "",
    provider: ProviderOption = None,
    mode: ModeOption = None,
    set_options: SetOption = None,
    yes: YesOption = False,
    verbose: VerboseOption = False,
) -> None:
    """Stage 2: stability across the M runs, and across chunk lengths P (M11).

    One full run per P. Every P changes the chunks, so no P reuses another's answers; the plan
    prints the cost first and nothing is sent without --yes.
    """
    from mmlsa.corpus.loader import CorpusError
    from mmlsa.experiments.sensitivity import SensitivityError, plan_sweep, run_sweep
    from mmlsa.pipeline.noise import NoiseError
    from mmlsa.pipeline.orchestrator import RunError, build_run_id

    configure_logging(verbose=verbose)
    resolved = _load(config, provider, mode, None, set_options)
    sweep = sweep_id or build_run_id(resolved)
    try:
        plan = plan_sweep(resolved, sweep)
    except (SensitivityError, CorpusError, NoiseError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"sweep           {sweep}")
    typer.echo(f"config          {config}")
    typer.echo(f"provider        {resolved.llm.provider}  (mode: {resolved.llm.mode})")
    typer.echo(
        f"runs            M = {resolved.run.M} at each P; (a) is read at P = {resolved.chunking.P}"
    )
    for size, member in plan.members:
        typer.echo(
            f"  P = {size:<5}     {member.total_calls:>7,} calls, {member.cached_calls:,} already saved"
        )
    typer.secho(f"NEW CALLS       {plan.calls_to_issue:,} of {plan.total_calls:,}", bold=True)

    if not yes:
        typer.echo(
            "\nNothing was requested. Re-run with --yes to issue these calls, and with "
            f"--sweep-id {sweep} to continue this sweep later."
        )
        return

    try:
        result = run_sweep(resolved, sweep)
    except (SensitivityError, RunError, CorpusError, NoiseError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    typer.echo("")
    typer.secho(f"sweep {result.sweep_id}", bold=True)
    typer.echo(f"artifacts       {result.sweep_dir}")
    typer.echo(f"(a) runs        {result.stability}")
    typer.echo(f"(b) P           {result.p_sweep}")
    typer.echo(f"recommendation  {result.recommendation}")
    typer.secho(f"verdict         {result.verdict}", bold=True)


@experiment_app.command("noise")
def experiment_noise(
    config: ConfigOption,
    with_noise: Annotated[
        str, typer.Option("--with-noise", help="The finished run with noise injection.")
    ],
    without_noise: Annotated[
        str,
        typer.Option(
            "--without-noise",
            help="The same run with --set noise.enabled=false.",
        ),
    ],
    set_options: SetOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Validation check 4: do labels hold with and without noise injection? No calls (M14)."""
    from mmlsa.experiments import validation

    configure_logging(verbose=verbose)
    resolved = _load(config, None, None, None, set_options)
    try:
        result = validation.run_noise(resolved, with_noise, without_noise)
    except validation.CheckError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    _report_check(result)


if __name__ == "__main__":
    app()
