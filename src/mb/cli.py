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


@fetch_app.command("delivery")
def fetch_delivery(
    data_config: DataCfg,
    start: Annotated[str, typer.Option("--from", help="First date, YYYY-MM-DD.")],
    end: Annotated[str, typer.Option("--to", help="Last date, YYYY-MM-DD.")],
    root: Root = _ROOT,
) -> None:
    """Download missing delivery-position files for the sessions in the bhavcopy store. Existing files are kept."""
    from mb.config.loader import load_data_config
    from mb.config.models import DataConfigM40
    from mb.sources import nse_bhavcopy, nse_delivery

    try:
        cfg, _ = load_data_config(data_config)
        if not isinstance(cfg, DataConfigM40):
            raise ValueError("the data config has no delivery section")
        lo, hi = date.fromisoformat(start), date.fromisoformat(end)
        sessions = [d for z in nse_bhavcopy.list_zips(root / cfg.bhavcopy.raw_dir)
                    if lo <= (d := nse_bhavcopy.zip_date(z)) <= hi]
        res = nse_delivery.fetch(cfg.delivery, root / cfg.delivery.raw_dir, sessions)
    except (ConfigError, ValueError) as e:
        raise _fail(str(e)) from None
    typer.echo(f"downloaded {len(res['downloaded'])}, not published {len(res['missing'])}: "
               f"{[d.isoformat() for d in res['missing']][:20]}")


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
    merged, failed = nse_corporate_actions.fetch(cfg.corporate_actions, root, start_year, end_year)
    typer.echo(f"{merged.height} corporate actions in {cfg.corporate_actions.raw_file}")
    if failed:
        raise _fail(f"windows starting {', '.join(map(str, failed))} failed and kept their previous data")


@fetch_app.command("industry")
def fetch_industry(
    industry_config: Annotated[Path, typer.Argument(help="Industry source YAML (configs/data/nse_industry.yaml).")],
    root: Root = _ROOT,
) -> None:
    """Snapshot NSE's industry classification for today's listed symbols (one immutable file per day)."""
    from mb.config.loader import load_industry_config
    from mb.sources import nse_industry

    try:
        cfg = load_industry_config(industry_config)
        out, failed = nse_industry.fetch(cfg, root, date.today())
    except (ConfigError, ValueError) as e:
        raise _fail(str(e)) from None
    typer.echo(f"wrote {out}; failed {len(failed)}: {failed[:20]}")


@fetch_app.command("pledges")
def fetch_pledges(
    pledge_config: Annotated[Path, typer.Argument(help="Pledge source YAML (configs/data/nse_pledges.yaml).")],
    first: Annotated[str, typer.Option("--from", help="First month, YYYY-MM.")],
    last: Annotated[str, typer.Option("--to", help="Last month, YYYY-MM.")],
    root: Root = _ROOT,
) -> None:
    """Fetch NSE's SAST Reg 31 pledge events, one immutable file per ended month (existing months are skipped)."""
    from mb.config.loader import load_pledge_config
    from mb.sources import nse_pledges

    try:
        cfg = load_pledge_config(pledge_config)
        written, skipped, failed = nse_pledges.fetch(cfg, root, first, last, date.today())
    except (ConfigError, ValueError) as e:
        raise _fail(str(e)) from None
    typer.echo(f"wrote {len(written)} months, skipped {len(skipped)}")
    if failed:
        raise _fail(f"months failed: {', '.join(failed)}")


@fetch_app.command("dhan-scrips")
def fetch_dhan_scrips(
    live_config: Annotated[Path, typer.Argument(help="Live config YAML (configs/live/dhan_m106.yaml).")],
    root: Root = _ROOT,
) -> None:
    """Snapshot Dhan's public scrip master (security ids; one immutable file per day)."""
    from mb.config.loader import load_live_config
    from mb.sources import dhan_scrips

    try:
        out = dhan_scrips.fetch(load_live_config(live_config).scrips, root, date.today())
    except (ConfigError, ValueError) as e:
        raise _fail(str(e)) from None
    typer.echo(f"wrote {out}")


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


paper_app = typer.Typer(no_args_is_help=True)
app.add_typer(paper_app, name="paper", help="Daily paper trading.")
PaperCfg = Annotated[Path, typer.Argument(help="Paper config YAML, e.g. configs/paper/momentum_voladj_stocks.yaml.")]


@paper_app.command("daily")
def paper_daily(
    paper_config: PaperCfg,
    fetch: Annotated[bool, typer.Option("--fetch/--no-fetch", help="Download and rebuild first (off: newest dataset).")] = True,
    today: Annotated[str | None, typer.Option("--today", help="Run as of this date, YYYY-MM-DD (default: today in IST).")] = None,
    root: Root = _ROOT,
) -> None:
    """Update data, advance the paper book, replay the backtest and alert. Exit 1 means something needs a person."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from mb.live import daily
    from mb.live.alerts import Alerter
    from mb.config.loader import load_paper_config

    day = date.fromisoformat(today) if today else datetime.now(ZoneInfo("Asia/Kolkata")).date()
    try:
        code = daily.run(paper_config, root, day, fetch)
    except ConfigError as e:
        raise _fail(str(e)) from None
    except Exception as e:  # noqa: BLE001 - a crash must still reach the phone
        try:
            cfg, _ = load_paper_config(paper_config, root)
            Alerter(cfg.alerts).send(f"{cfg.name}: daily job crashed", f"{type(e).__name__}: {e}", "high", ("rotating_light",))
        finally:
            raise
    typer.echo(daily.status(paper_config, root))
    raise typer.Exit(code)


@paper_app.command("status")
def paper_status(paper_config: PaperCfg, root: Root = _ROOT) -> None:
    """The book, pending orders and the latest replay."""
    from mb.live import daily

    try:
        typer.echo(daily.status(paper_config, root))
    except ConfigError as e:
        raise _fail(str(e)) from None


live_app = typer.Typer(no_args_is_help=True)
app.add_typer(live_app, name="live", help="Offline Dhan order plans and holdings checks (M137; nothing is sent).")
LiveCfg = Annotated[Path, typer.Argument(help="Live config YAML, e.g. configs/live/dhan_m106.yaml.")]
PaperRoot = Annotated[Path | None, typer.Option("--paper-root", help="Checkout whose data/paper/ holds the book (default: --root).")]
Holdings = Annotated[Path | None, typer.Option("--holdings", help="Saved Dhan GET /holdings response (JSON list).")]


def _live(live_config: Path, root: Path, paper_root: Path | None):  # noqa: ANN202
    from mb.config.loader import load_live_config, load_paper_config
    from mb.live.paper import Store

    cfg = load_live_config(live_config)
    pcfg, _ = load_paper_config(root / cfg.paper_config, root)
    return cfg, pcfg, Store(paper_root or root, pcfg.name)


@live_app.command("plan")
def live_plan(
    live_config: LiveCfg,
    decided: Annotated[str | None, typer.Option("--decided", help="Plan a past decision, YYYY-MM-DD (default: the pending orders).")] = None,
    holdings: Holdings = None,
    paper_root: PaperRoot = None,
    root: Root = _ROOT,
) -> None:
    """Dhan order bodies for the paper book's decision at the live capital -> data/live/<name>/plans/. Exit 1: refused."""
    import json

    from mb.live import broker
    from mb.sources import dhan_scrips

    try:
        cfg, pcfg, store = _live(live_config, root, paper_root)
        if decided is None:
            book = store.load_book(pcfg)
            if not book.pending:
                raise _fail(f"{pcfg.name}: no pending orders (use --decided for a past decision)")
            decided = book.pending["decided"]
            rec = json.loads((store.dir / "days" / f"{decided}.json").read_text())
            want = [{k: o[k] for k in ("symbol", "side", "shares")} for o in rec["decision"]["orders"]]
            if want != book.pending["orders"]:
                raise _fail(f"{pcfg.name}: pending orders differ from days/{decided}.json")
        else:
            f = store.dir / "days" / f"{decided}.json"
            if not f.exists():
                raise _fail(f"no paper day record {f}")
            rec = json.loads(f.read_text())
        src = dhan_scrips.newest(cfg.scrips, root)
        held = broker.holdings_qty(json.loads(holdings.read_text())) if holdings else None
        p = broker.plan(cfg, broker.decision_from_day(rec), dhan_scrips.load(cfg.scrips, src), root, held)
        out = broker.write(p, src.name, root)
    except broker.Refused as e:
        raise _fail("plan refused:\n" + "\n".join(f"  {r}" for r in e.reasons)) from None
    except (ConfigError, ValueError) as e:
        raise _fail(str(e)) from None
    typer.echo(out.read_text())


@live_app.command("reconcile")
def live_reconcile(
    live_config: LiveCfg,
    holdings: Annotated[Path, typer.Option("--holdings", help="Saved Dhan GET /holdings response (JSON list).")],
    paper_root: PaperRoot = None,
    root: Root = _ROOT,
) -> None:
    """Broker holdings vs the paper book. Exit 1 on any mismatch."""
    import json

    from mb.live import broker

    try:
        cfg, pcfg, store = _live(live_config, root, paper_root)
        book = store.load_book(pcfg)
        gaps = broker.reconcile(cfg, {s: (p.shares, p.last_close) for s, p in book.positions.items()},
                                broker.holdings_qty(json.loads(holdings.read_text())))
    except (ConfigError, ValueError) as e:
        raise _fail(str(e)) from None
    if gaps:
        raise _fail(f"{pcfg.name} (book as of {book.as_of}): {len(gaps)} mismatches\n" + "\n".join(f"  {g}" for g in gaps))
    typer.echo(f"{pcfg.name}: broker holdings match the paper book as of {book.as_of} ({len(book.positions)} names)")


vcp_app = typer.Typer(no_args_is_help=True)
app.add_typer(vcp_app, name="vcp", help="VCP pattern tools.")


@vcp_app.command("check")
def vcp_check(
    config: Annotated[Path, typer.Argument(help="VCP strategy config YAML.")],
    sample: Annotated[int, typer.Option("--sample", help="Breakouts to chart.")] = 30,
    seed: Annotated[int, typer.Option("--seed", help="Random seed for the sample.")] = 1,
    root: Root = _ROOT,
) -> None:
    """Funnel and sampled breakout charts, drawn up to the breakout day (no returns) -> reports/vcp-check/<version>/."""
    from mb.strategy.vcp import check

    try:
        cfg = load_strategy_config(config, root)
        enforce_lock(cfg, False)
    except ConfigError as e:
        raise _fail(str(e)) from None
    page = check.write(cfg, root, root / "reports" / "vcp-check" / cfg.strategy.version, sample, seed)
    typer.echo(page.with_name("funnel.md").read_text())
    typer.echo(f"charts {page}")


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
