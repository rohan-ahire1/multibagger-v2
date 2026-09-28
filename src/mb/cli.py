from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from mb.config.loader import ConfigError, enforce_lock, load_strategy_config
from mb.runs import record
from mb.strategy.registry import runner

app = typer.Typer(no_args_is_help=True, add_completion=False)
runs_app = typer.Typer(no_args_is_help=True)
app.add_typer(runs_app, name="runs", help="Inspect run records.")

Root = Annotated[Path, typer.Option("--root", help="Repo root holding configs/ and runs/.")]
_ROOT = Path(__file__).resolve().parents[2]


@app.command()
def backtest(
    config: Annotated[Path, typer.Argument(help="Strategy config YAML.")],
    final: Annotated[bool, typer.Option("--final", help="Allow the locked test period.")] = False,
    root: Root = _ROOT,
) -> None:
    """Run one backtest and write its run record."""
    try:
        cfg = load_strategy_config(config, root)
        enforce_lock(cfg, final)
    except ConfigError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from None
    started = record.now()
    result = runner(cfg.strategy.name)(cfg)
    out = record.write_run(cfg, result, root, root / "runs", final, started, record.now())
    typer.echo(f"run {out.name}")
    typer.echo(f"config {config} (hash {cfg.hash()[:8]})")


@runs_app.command("list")
def runs_list(root: Root = _ROOT) -> None:
    """List all runs (index rebuilt from run folders)."""
    typer.echo(str(record.list_runs(root / "runs")))
