"""M147 shadow book: a pinned strategy config re-run each evening over [start, newest session] on the daily dataset.

For strategies the paper engine cannot trade yet (the M142 blend's daily pullback sleeve). Every session is decided
from data up to its own close, so the forward record is out of sample. Each session's equity is recorded once; a later
run on a rebuilt dataset that moves a recorded session by more than `max_restated_equity_pct` is alerted and the
recorded value kept.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from mb.config.loader import Resolved, load_data_config, load_shadow_config
from mb.config.models import Period, ShadowConfig
from mb.data import datasets
from mb.live import calendar
from mb.live.alerts import Alerter
from mb.live.daily import latest_ref
from mb.live.paper import write_json
from mb.strategy.blend.params import Params as BlendParams
from mb.strategy.blend.params import ParamsM110 as BlendParamsM110
from mb.strategy.blend.run import load_sleeves, mix, mix_rebalanced
from mb.engine.gate import DataGateError, enforce_data_gate
from mb.engine.run import JUMPS_FILE, load_bars, load_sectors
from mb.engine.simulate import simulate as simulate_signals
from mb.runs.record import RunResult
from mb.strategy.momentum import params as momentum
from mb.strategy.momentum.run import simulate as simulate_momentum
from mb.strategy.pullback import run as pullback


def on(sc: Resolved, ref: str, start: date, end: date) -> Resolved:
    """The same config over [start, end] on `ref`; params, market and baselines unchanged."""
    return dataclasses.replace(sc, strategy=sc.strategy.model_copy(update={"period": Period(start=start, end=end),
                                                                           "dataset": ref}))


def sleeve(cfg: Resolved, root: Path) -> RunResult:
    """The strategy's simulation and data gate without the run's metrics: the folds and the Nifty 500 TRI baseline
    do not reach a few weeks of forward data."""
    p = cfg.params
    ds = datasets.dataset_path(root, cfg.strategy.dataset)
    if isinstance(p, momentum.Params):
        res = simulate_momentum(cfg, root)
        equity, trades = res.equity, res.holdings
    elif isinstance(p, pullback.Params):
        period = cfg.strategy.period
        panel = pl.scan_parquet(ds / datasets.PANEL_FILE).filter(pl.col("date") <= period.end).collect()
        sigs = pullback.signals(pullback.features(panel, p), p, period.start, period.end)
        res = simulate_signals(sigs, load_bars(root, cfg, p.engine), load_sectors(root, cfg), p.engine, cfg.market)
        equity, trades = res.equity, res.trades
    else:
        raise ValueError(f"shadow books support momentum and pullback sleeves, not {cfg.strategy.name}")
    enforce_data_gate(trades, pl.read_parquet(ds / JUMPS_FILE))
    return RunResult(metrics={}, trades=trades, equity=equity)


def simulate(strat: Resolved, root: Path, ref: str, start: date, end: date
             ) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, pl.DataFrame], list[tuple[str, Resolved]]]:
    """Equity curve, trades (with a `sleeve` column), each sleeve's own curve, and the configs that ran."""
    p = strat.params
    if not isinstance(p, BlendParams):
        cfg = on(strat, ref, start, end)
        r = sleeve(cfg, root)
        name = cfg.strategy.version
        return r.equity, r.trades.with_columns(pl.lit(name).alias("sleeve")), {name: r.equity}, [(name, cfg)]
    ran = [(sc.strategy.version, w, on(sc, ref, start, end)) for w, sc in load_sleeves(strat, root)]
    sleeves = [(name, w, sleeve(cfg, root)) for name, w, cfg in ran]
    if isinstance(p, BlendParamsM110) and p.rebalance == "monthly":
        equity, trades, _, _ = mix_rebalanced(sleeves, p.initial_capital, strat.market)
    else:
        equity, trades, _ = mix(sleeves, p.initial_capital)
    return equity, trades, {name: r.equity for name, _, r in sleeves}, [(name, cfg) for name, _, cfg in ran]


def setups(cfg: Resolved, root: Path, day: date) -> list[dict[str, Any]]:
    """A pullback sleeve's signals at `day`'s close: limit buys for the next open, best first."""
    p = cfg.params
    assert isinstance(p, pullback.Params)
    panel = (pl.scan_parquet(datasets.dataset_path(root, cfg.strategy.dataset) / datasets.PANEL_FILE)
             .filter(pl.col("date") <= day).collect())
    s = pullback.signals(pullback.features(panel, p), p, day, day).head(p.engine.sizing.max_positions)
    return [{"symbol": r["symbol"], "limit": round(r["entry_ref"], 2), "rsi": round(r["rsi"], 1)} for r in s.iter_rows(named=True)]


def open_positions(trades: pl.DataFrame) -> dict[str, list[str]]:
    if "status" not in trades.columns:
        return {}
    o = trades.filter(pl.col("status") == "open")
    return {s: sorted(o.filter(pl.col("sleeve") == s)["symbol"].to_list()) for s in sorted(o["sleeve"].unique().to_list())}


def positions(trades: pl.DataFrame) -> list[dict[str, Any]]:
    """Open positions marked at the last close: sleeve, symbol, entry date and gain since entry."""
    if "status" not in trades.columns:
        return []
    o = trades.filter(pl.col("status") == "open").sort("sleeve", "symbol")
    return [{"sleeve": r["sleeve"], "symbol": r["symbol"], "entry": r["entry_date"].isoformat(),
             "gain_pct": None if r["return_pct"] is None else round(r["return_pct"], 2)}
            for r in o.select("sleeve", "symbol", "entry_date", "return_pct").iter_rows(named=True)]


def _sessions_path(cfg: ShadowConfig, root: Path) -> Path:
    return root / "data" / "paper" / cfg.name / "sessions.json"


def recorded(cfg: ShadowConfig, root: Path) -> dict[str, dict[str, Any]]:
    path = _sessions_path(cfg, root)
    return json.loads(path.read_text()) if path.exists() else {}


def run(cfg_path: Path, root: Path, today: date, alerter: Alerter | None = None) -> int:
    """0 when clean, 1 when something needs a person (every problem was alerted)."""
    cfg, strat = load_shadow_config(cfg_path, root)
    dcfg, _ = load_data_config(root / cfg.data_config)
    alerter = alerter or Alerter(cfg.alerts)
    out = root / "data" / "paper" / cfg.name
    problems: list[str] = []
    log: dict[str, Any] = {"started_at": datetime.now(UTC).isoformat(), "today": today.isoformat()}

    ref = latest_ref(root, dcfg.name)
    log["dataset"] = ref
    if ref is None:
        return _finish(cfg, out, alerter, ["no daily dataset"], log, today)
    holidays = calendar.load(cfg.calendar, root)
    last = date.fromisoformat(datasets.read_manifest(datasets.dataset_path(root, ref))["date_max"])
    missing = calendar.trading_days_between(last, today, holidays)
    log["last_session"], log["missing_sessions"] = last.isoformat(), [d.isoformat() for d in missing]
    if len(missing) > cfg.max_missing_sessions:
        problems.append(f"stale data: newest session {last}; missing {', '.join(map(str, missing))}")
    if last < cfg.start:
        log["note"] = f"book starts {cfg.start}; newest session {last}"
        return _finish(cfg, out, alerter, problems, log, today)

    try:
        equity, trades, curves, ran = simulate(strat, root, ref, cfg.start, last)
    except DataGateError as e:
        return _finish(cfg, out, alerter, problems + [f"data gate refused the run on {ref}: {e}"], log, today)
    rec = recorded(cfg, root)
    added, restated = [], []
    sleeve_eq = {n: dict(zip(c["date"].to_list(), c["equity"].to_list())) for n, c in curves.items()}
    for d, eq, inv in equity.filter(pl.col("date") >= cfg.start).select("date", "equity", "invested_value").iter_rows():
        k = d.isoformat()
        if k in rec:
            move = (eq / rec[k]["equity"] - 1) * 100
            if abs(move) > cfg.max_restated_equity_pct:
                restated.append(f"{k} {move:+.2f}%")
            continue
        rec[k] = {"equity": eq, "invested": inv, "dataset": ref, "sleeves": {n: e[d] for n, e in sleeve_eq.items() if d in e}}
        added.append(k)
    if restated:
        problems.append(f"recorded sessions moved on {ref}: " + ", ".join(restated))
    write_json(_sessions_path(cfg, root), rec)

    pending = {n: setups(c, root, last) for n, c in ran if isinstance(c.params, pullback.Params)}
    held = open_positions(trades)
    entered = trades.filter(pl.col("entry_date") == last).select("sleeve", "symbol").rows() if trades.height else []
    exited = (trades.filter((pl.col("exit_date") == last) & (pl.col("status") != "open")).select("sleeve", "symbol").rows()
              if trades.height and "status" in trades.columns else [])
    latest = {"as_of": last.isoformat(), "dataset": ref, "equity": rec[last.isoformat()]["equity"],
              "return_pct": (rec[last.isoformat()]["equity"] / equity["equity"][0] - 1) * 100 if equity.height else 0.0,
              "held": held, "positions": positions(trades), "entered": entered, "exited": exited, "next_open_limit_buys": pending}
    write_json(out / "latest.json", latest)
    log["added"], log["latest"] = added, latest
    if added and (pending and any(pending.values()) or entered or exited or calendar.is_month_end(last, holidays)):
        _push(cfg, latest, calendar.is_month_end(last, holidays), alerter)
    if not problems and today.weekday() == cfg.alerts.heartbeat_weekday and not (out / "daily" / f"heartbeat-{today}").exists():
        alerter.send(f"{cfg.name}: weekly ok", f"Data through {last}. Equity Rs {latest['equity']:,.0f} "
                     f"({latest['return_pct']:+.2f}%), {sum(len(v) for v in held.values())} positions.", "low", ("white_check_mark",))
        (out / "daily").mkdir(parents=True, exist_ok=True)
        (out / "daily" / f"heartbeat-{today}").write_text("")
    return _finish(cfg, out, alerter, problems, log, today)


def _push(cfg: ShadowConfig, latest: dict[str, Any], month_end: bool, alerter: Alerter) -> None:
    lines = [f"Close {latest['as_of']}: equity Rs {latest['equity']:,.0f} ({latest['return_pct']:+.2f}%)."]
    if latest["entered"]:
        lines.append("Bought today: " + ", ".join(f"{s} ({n})" for n, s in latest["entered"]))
    if latest["exited"]:
        lines.append("Sold today: " + ", ".join(f"{s} ({n})" for n, s in latest["exited"]))
    for n, buys in latest["next_open_limit_buys"].items():
        if buys:
            lines.append(f"Limit buys for the next session ({n}): " + ", ".join(f"{b['symbol']} @ {b['limit']:,}" for b in buys))
    if month_end:
        lines.append("Month-end: the momentum sleeve rebalances at the next open; sleeves reset to their weights.")
    alerter.send(f"{cfg.name}: today", "\n".join(lines), "default", ("chart_with_upwards_trend",))


def _finish(cfg: ShadowConfig, out: Path, alerter: Alerter, problems: list[str], log: dict, today: date) -> int:
    log["problems"] = problems
    log["finished_at"] = datetime.now(UTC).isoformat()
    write_json(out / "daily" / f"{today}-{datetime.now(UTC):%H%M%S}.json", log)
    if problems:
        alerter.send(f"{cfg.name}: needs attention", "\n".join(f"- {p}" for p in problems), "high", ("warning",))
        return 1
    return 0


def status(cfg_path: Path, root: Path) -> str:
    cfg, _ = load_shadow_config(cfg_path, root)
    path = root / "data" / "paper" / cfg.name / "latest.json"
    if not path.exists():
        return f"{cfg.name}: not started (start {cfg.start})"
    s = json.loads(path.read_text())
    lines = [f"{cfg.name}: as of {s['as_of']} on {s['dataset']}",
             f"equity {s['equity']:,.2f}  return {s['return_pct']:+.2f}%"]
    lines += [f"held ({n}): {', '.join(v) or '-'}" for n, v in s["held"].items()]
    lines += [f"next-open limit buys ({n}): {', '.join(b['symbol'] for b in v) or '-'}" for n, v in s["next_open_limit_buys"].items()]
    return "\n".join(lines)
