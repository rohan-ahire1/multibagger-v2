"""Hedged runner (M139, docs/research/m139.md): a momentum book plus short index futures while the market is risk-off.

The base book runs unchanged (its own regime switch must be off). At each of its decision dates the signal is read at
the close; from the next session's open the book is short `ratio` x (book equity at that close) of the nearest futures
contract with more than `roll_sessions` sessions left, or flat when risk-on. The rupee notional is kept through rolls.
Hedge P&L is cash beside the base book (earning nothing, like the base's idle cash): book = base equity + hedge cash.
Fractional contracts; margin and daily mark-to-market cash are not modelled.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from mb.config.loader import ConfigError, Resolved, enforce_lock, load_strategy_config
from mb.data import datasets
from mb.engine.run import score
from mb.evaluation.metrics import exposure_metrics
from mb.runs.record import RunResult
from mb.sources.nse_fo_bhav import futures
from mb.strategy.hedged.params import Hedge, Params

__all__ = ["Params", "run", "overlay"]


@dataclass
class OverlayResult:
    pnl: dict[date, float]        # hedge P&L of each session, costs included
    cost: float
    short_sessions: int           # sessions that end short
    rolls: int
    stale_prices: int             # sessions a held contract had no close (P&L 0 that day)


def _sessions_left(days: list[date], d: date, expiry: date) -> int:
    """Sessions after d up to and including expiry (beyond the calendar's end: counted as unbounded)."""
    if expiry > days[-1]:
        return 10**9
    return bisect.bisect_right(days, expiry) - bisect.bisect_right(days, d)


def overlay(base: list[tuple[date, float]], decisions: dict[date, bool], fut: pl.DataFrame, h: Hedge) -> OverlayResult:
    """`base`: (session, base book equity) for every session; `decisions`: decision date -> risk-on; `fut`: d, expiry,
    o, c of the futures symbol."""
    days = [d for d, _ in base]
    px: dict[date, dict[date, tuple[float | None, float]]] = {}
    for d, e, o, c in fut.select("d", "expiry", "o", "c").iter_rows():
        px.setdefault(d, {})[e] = (o, c)
    k = h.cost_bps_per_side / 1e4
    q, contract, last = 0.0, None, 0.0     # contracts short (index units), their expiry, the last close used
    cash, cost, short_sessions, rolls, stale = 0.0, 0.0, 0, 0, 0
    pnl: dict[date, float] = {}
    pending: float | None = None           # notional wanted from this session's open (0 = flat)

    def pick(d: date) -> date:
        ok = sorted(e for e in px.get(d, {}) if _sessions_left(days, d, e) > h.roll_sessions)
        if not ok:
            raise ValueError(f"no {h.futures_symbol} futures contract with > {h.roll_sessions} sessions left on {d}")
        return ok[0]

    for d, eq in base:
        today = 0.0
        if pending is not None:
            want = pending
            if q > 0.0:                        # mark the held contract to this open (or carry if no row)
                assert contract is not None
                row = px.get(d, {}).get(contract)
                o = row[0] if row and row[0] is not None else (row[1] if row else last)
                today -= q * (o - last)
                last, held_notional = o, q * o
            else:
                held_notional = 0.0
            if want > 0.0:
                new = contract if q > 0.0 and contract is not None and _sessions_left(days, d, contract) > h.roll_sessions else pick(d)
                row = px[d][new]
                o = row[0] if row[0] is not None else row[1]
                traded = abs(want - held_notional) if new == contract else want + held_notional
                q, contract, last = want / o, new, o
            else:
                traded, q, contract = held_notional, 0.0, None
            today -= k * traded
            cost += k * traded
            pending = None
        if q > 0.0:
            assert contract is not None
            row = px.get(d, {}).get(contract)
            if row is None:
                stale += 1
            else:
                today -= q * (row[1] - last)
                last = row[1]
            if _sessions_left(days, d, contract) <= h.roll_sessions:   # roll at this close, notional kept
                notional = q * last
                new = pick(d)
                q, contract, last = notional / px[d][new][1], new, px[d][new][1]
                today -= 2 * k * notional
                cost += 2 * k * notional
                rolls += 1
            short_sessions += 1
        cash += today
        pnl[d] = today
        if d in decisions:
            pending = 0.0 if decisions[d] else h.ratio * (eq + cash)
    return OverlayResult(pnl, cost, short_sessions, rolls, stale)


def load_base(cfg: Resolved, root: Path) -> Resolved:
    """The base config, refused if its hash changed, it is not momentum, its switch is on, or it differs from the
    hedged config in period, dataset or market."""
    p = cfg.params
    assert isinstance(p, Params)
    sc = load_strategy_config(root / p.base.config, root)
    if sc.hash() != p.base.config_hash:
        raise ConfigError(f"base {p.base.config}: config hash {sc.hash()[:8]} differs from the pinned {p.base.config_hash[:8]}")
    if sc.strategy.name != "momentum":
        raise ConfigError(f"base {p.base.config}: must be a momentum config")
    bp = sc.params
    if bp.regime.enabled or getattr(bp.schedule, "every_sessions", None) is not None:  # type: ignore[attr-defined]
        raise ConfigError(f"base {p.base.config}: needs regime.enabled false and month-end decisions")
    for field in ("period", "dataset", "market"):
        if getattr(sc.strategy, field) != getattr(cfg.strategy, field):
            raise ConfigError(f"base {p.base.config}: {field} differs from the hedged config's")
    if cfg.strategy.period.end < cfg.baselines.locked_from:
        enforce_lock(sc, final=False)
    return sc


def run(cfg: Resolved, root: Path) -> RunResult:
    from mb.strategy.momentum.run import simulate
    from mb.strategy.momentum.targets import decision_dates, risk_on

    p = cfg.params
    assert isinstance(p, Params)
    period = cfg.strategy.period
    sc = load_base(cfg, root)
    res = simulate(sc, root)
    panel = (pl.scan_parquet(datasets.dataset_path(root, cfg.strategy.dataset) / datasets.PANEL_FILE)
             .filter(pl.col("date") <= period.end).select("date", "symbol", "adj_close").collect())
    offset = sc.params.schedule.decision_offset_sessions  # type: ignore[attr-defined]
    dates = decision_dates(panel.select("date").unique(), period.start, period.end, offset)
    on = risk_on(panel, p.hedge.signal_symbol, p.hedge.sma_sessions, dates)
    fut = futures(root / p.hedge.futures_raw_dir, p.hedge.futures_symbol, period.start, period.end)
    eq = res.equity.sort("date")
    ov = overlay(list(zip(eq["date"].to_list(), eq["equity"].to_list())), on, fut, p.hedge)
    h = pl.DataFrame({"date": list(ov.pnl), "h": list(ov.pnl.values())}).with_columns(pl.col("h").cum_sum())
    equity = eq.join(h, on="date", how="left").with_columns(pl.col("h").fill_null(0.0)).with_columns(
        pl.col("equity") + pl.col("h"), pl.col("cash") + pl.col("h")).drop("h")
    fills = res.fills.filter(pl.col("date").is_between(period.start, period.end))
    traded = (fills["shares"] * fills["price"]).sum() if fills.height else 0.0
    exposure = exposure_metrics(equity, traded, period.start, period.end)
    extra = {"rebalances": res.rebalances,
             "hedge": {"risk_off_decisions": sum(not v for v in on.values()), "decisions": len(on),
                       "short_sessions": ov.short_sessions, "rolls": ov.rolls, "stale_prices": ov.stale_prices,
                       "pnl_inr": sum(ov.pnl.values()), "cost_inr": ov.cost}}
    return score(cfg, root, equity, res.holdings, exposure, extra)
