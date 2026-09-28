from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from datetime import date

from mb.config.loader import ConfigError, enforce_lock, load_strategy_config
from mb.runs import record, research
from mb.strategy.registry import runner

app = typer.Typer(no_args_is_help=True, add_completion=False)
runs_app = typer.Typer(no_args_is_help=True)
app.add_typer(runs_app, name="runs", help="Inspect run records.")
research_app = typer.Typer(no_args_is_help=True)
app.add_typer(research_app, name="research", help="Compare variants against the pinned milestone.")
data_app = typer.Typer(no_args_is_help=True)
app.add_typer(data_app, name="data", help="Fetch, build and check datasets.")
fetch_app = typer.Typer(no_args_is_help=True)
data_app.add_typer(fetch_app, name="fetch", help="Download into the raw store.")

Root = Annotated[Path, typer.Option("--root", help="Repo root holding configs/ and runs/.")]
_ROOT = Path(__file__).resolve().parents[2]


@app.command()
def backtest(
    config: Annotated[Path, typer.Argument(help="Strategy config YAML.")],
    final: Annotated[bool, typer.Option("--final", help="Allow the locked test period.")] = False,
    question: Annotated[str | None, typer.Option("--question", help="Research question this run belongs to (counts variants).")] = None,
    root: Root = _ROOT,
) -> None:
    """Run one backtest and write its run record."""
    try:
        cfg = load_strategy_config(config, root)
        enforce_lock(cfg, final)
        if final:
            research.check_final_unused(root / "runs", cfg.hash())
    except ConfigError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    started = record.now()
    result = runner(cfg.strategy.name)(cfg, root)
    out = record.write_run(cfg, result, root, root / "runs", final, started, record.now(), question)
    typer.echo(f"run {out.name}")
    typer.echo(f"config {config} (hash {cfg.hash()[:8]})")


@runs_app.command("list")
def runs_list(root: Root = _ROOT) -> None:
    """List all runs (index rebuilt from run folders)."""
    typer.echo(str(record.list_runs(root / "runs")))


@runs_app.command("pin")
def runs_pin(
    run_id: Annotated[str, typer.Argument(help="Run id.")],
    name: Annotated[str, typer.Option("--as", help="Milestone name, e.g. sepa/2026-10_baseline.")],
    root: Root = _ROOT,
) -> None:
    """Mark a run as a milestone. Refuses runs from uncommitted code and never moves an existing pin."""
    try:
        research.pin(root / "runs", run_id, name)
    except ConfigError as e:
        raise _fail(str(e)) from None
    typer.echo(f"pinned {name} -> {run_id}")


@runs_app.command("diff")
def runs_diff(
    a: Annotated[str, typer.Argument(help="Run id or pin name.")],
    b: Annotated[str, typer.Argument(help="Run id or pin name.")],
    root: Root = _ROOT,
) -> None:
    """Show which config values, data or code changed between two runs, and how the headline numbers moved."""
    try:
        typer.echo("\n".join(research.diff(root / "runs", a, b)))
    except ConfigError as e:
        raise _fail(str(e)) from None


@runs_app.command("verify")
def runs_verify(
    ref: Annotated[str, typer.Argument(help="Run id or pin name.")],
    root: Root = _ROOT,
) -> None:
    """Re-run a non-final run and check the result matches the record exactly."""
    try:
        problems = research.verify(root / "runs", ref, root)
    except ConfigError as e:
        raise _fail(str(e)) from None
    if problems:
        raise _fail("; ".join(problems))
    typer.echo("re-run matches the record exactly")


@research_app.command("report")
def research_report(
    question: Annotated[str, typer.Argument(help="Research question id used with --question.")],
    against: Annotated[str, typer.Option("--against", help="Pin name or run id of the current milestone.")],
    root: Root = _ROOT,
) -> None:
    """Report every variant tried for a question and whether any passes the adoption bar."""
    try:
        from mb.config.loader import load_baselines
        text, adopted = research.report(root / "runs", question, against, load_baselines(root).adoption.metric)
    except ConfigError as e:
        raise _fail(str(e)) from None
    out = root / "reports" / f"{question}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text + "\n")
    typer.echo(text)
    typer.echo(f"written {out}; {'a variant passes the bar' if adopted else 'no variant passes the bar'}")


DataCfg = Annotated[Path, typer.Argument(help="Data config YAML, e.g. configs/data/nse_research.yaml.")]


def _fail(msg: str) -> "typer.Exit":
    typer.echo(f"error: {msg}", err=True)
    return typer.Exit(2)


@fetch_app.command("bhavcopy")
def fetch_bhavcopy(
    data_config: DataCfg,
    start: Annotated[str, typer.Option("--from", help="First date, YYYY-MM-DD.")],
    end: Annotated[str, typer.Option("--to", help="Last date, YYYY-MM-DD.")],
    root: Root = _ROOT,
) -> None:
    """Download missing bhavcopy zips. Existing files are never overwritten."""
    from mb.config.loader import load_data_config
    from mb.sources import nse_bhavcopy

    try:
        cfg, _ = load_data_config(data_config)
        res = nse_bhavcopy.fetch(cfg.bhavcopy, root / cfg.bhavcopy.raw_dir, date.fromisoformat(start),
                                 date.fromisoformat(end))
    except (ConfigError, ValueError) as e:
        raise _fail(str(e)) from None
    typer.echo(f"downloaded {len(res['downloaded'])}, not published/holiday {len(res['missing'])}")


@fetch_app.command("corporate-actions")
def fetch_corporate_actions(
    data_config: DataCfg,
    start_year: Annotated[int, typer.Option(help="First year to fetch.")],
    end_year: Annotated[int, typer.Option(help="Last year to fetch.")],
    root: Root = _ROOT,
) -> None:
    """Fetch half-year windows and merge them into the raw corporate-action file."""
    from mb.config.loader import load_data_config
    from mb.sources import nse_corporate_actions

    try:
        cfg, _ = load_data_config(data_config)
    except ConfigError as e:
        raise _fail(str(e)) from None
    merged = nse_corporate_actions.fetch(cfg.corporate_actions, root, start_year, end_year)
    typer.echo(f"{merged.height} corporate actions in {cfg.corporate_actions.raw_file}")


@data_app.command("build")
def data_build(
    data_config: DataCfg,
    version: Annotated[str, typer.Option("--version", help="New dataset version label, e.g. 2026-09-29.")],
    root: Root = _ROOT,
) -> None:
    """Build a new immutable dataset version from the raw store, running all checks."""
    from mb.config.loader import load_data_config
    from mb.data import build as builder

    try:
        cfg, cfg_hash = load_data_config(data_config)
        out = builder.build(cfg, cfg_hash, root, version)
    except (ConfigError, builder.CheckFailure) as e:
        raise _fail(str(e)) from None
    typer.echo(f"built {cfg.name}@{version} -> {out}")


@data_app.command("check")
def data_check(
    dataset: Annotated[str, typer.Argument(help="<name>@<version>")],
    root: Root = _ROOT,
) -> None:
    """Show a dataset's recorded checks and verify its files against the manifest hashes."""
    from mb.data import datasets

    try:
        path = datasets.dataset_path(root, dataset)
        manifest = datasets.read_manifest(path)
    except (ConfigError, FileNotFoundError) as e:
        raise _fail(str(e)) from None
    for c in manifest["checks"]:
        typer.echo(f"{c['status']:8} {c['name']} = {c['value']} (limit {c['limit']}) {c['detail']}".rstrip())
    changed = datasets.verify_outputs(path)
    if changed:
        raise _fail(f"files differ from manifest hashes: {changed}")
    typer.echo("files match manifest hashes")
