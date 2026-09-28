"""Blend runner: run each sleeve's strategy, then mix the equity curves at fixed starting weights.

Sleeve i gets weight_i of the capital at the start and keeps its own P&L; there is no rebalancing between sleeves.
Blend equity = sum_i weight_i * capital * E_i(t) / E_i(start). Trades are the sleeves' trades with rupee columns scaled
the same way and a `sleeve` column.
"""
from __future__ import annotations

from datetime import date
from itertools import combinations
from pathlib import Path

import polars as pl

from mb.config.loader import ConfigError, Resolved, enforce_lock, load_strategy_config
from mb.engine.run import score
from mb.evaluation.metrics import exposure_metrics
from mb.runs.record import RunResult
from mb.strategy.blend.params import Params

__all__ = ["Params", "run", "load_sleeves", "mix"]

RUPEE_TRADE_COLUMNS = ("shares", "pnl", "bought", "sold")
CURVE_COLUMNS = ("equity", "cash", "invested_value")


def load_sleeves(cfg: Resolved, root: Path) -> list[tuple[float, Resolved]]:
    """Each sleeve config, refused if its hash changed or it differs from the blend in period, dataset or market."""
    p = cfg.params
    assert isinstance(p, Params)
    out = []
    for s in p.sleeves:
        sc = load_strategy_config(root / s.config, root)
        if sc.hash() != s.config_hash:
            raise ConfigError(f"sleeve {s.config}: config hash {sc.hash()[:8]} differs from the pinned {s.config_hash[:8]}")
        if sc.strategy.name == "blend":
            raise ConfigError(f"sleeve {s.config}: blends do not nest")
        for field in ("period", "dataset", "market"):
            if getattr(sc.strategy, field) != getattr(cfg.strategy, field):
                raise ConfigError(f"sleeve {s.config}: {field} differs from the blend's")
        if cfg.strategy.period.end < cfg.baselines.locked_from:
            enforce_lock(sc, final=False)  # a sleeve's settle window must not reach the locked period either
        out.append((s.weight, sc))
    return out


def mix(sleeves: list[tuple[str, float, RunResult]], capital: float) -> tuple[pl.DataFrame, pl.DataFrame, list[float]]:
    """Blend equity, scaled trades, and each sleeve's scale (rupees of blend per rupee of sleeve)."""
    curves, trades, scales = [], [], []
    for name, w, r in sleeves:
        k = w * capital / r.equity.sort("date")["equity"][0]
        scales.append(k)
        curves.append(r.equity.select("date", *(pl.col(c) * k for c in CURVE_COLUMNS), "open_positions"))
        t = r.trades.with_columns(pl.col(c) * k for c in RUPEE_TRADE_COLUMNS if c in r.trades.columns)
        trades.append(t.with_columns(pl.lit(name).alias("sleeve")))
    dates = [c["date"].to_list() for c in curves]
    if any(d != dates[0] for d in dates):
        raise ValueError("sleeve equity curves are on different session calendars")
    blend = curves[0].select("date").with_columns(
        *(pl.sum_horizontal(c[col] for c in curves).alias(col) for col in CURVE_COLUMNS),
        pl.sum_horizontal(c["open_positions"] for c in curves).alias("open_positions"))
    return blend, pl.concat(trades, how="diagonal_relaxed").sort("entry_date", "symbol", nulls_last=True), scales


def _daily_return_corr(sleeves: list[tuple[str, float, RunResult]], start: date, end: date) -> dict[str, float]:
    rets = {name: r.equity.filter(pl.col("date").is_between(start, end)).sort("date")["equity"].pct_change().drop_nulls()
            for name, _, r in sleeves}
    return {f"{a}|{b}": pl.DataFrame({"a": rets[a], "b": rets[b]}).select(pl.corr("a", "b")).item()
            for a, b in combinations(rets, 2)}


def run(cfg: Resolved, root: Path) -> RunResult:
    p = cfg.params
    assert isinstance(p, Params)
    from mb.strategy.registry import runner

    period = cfg.strategy.period
    sleeves = [(sc.strategy.version, w, runner(sc.strategy.name)(sc, root)) for w, sc in load_sleeves(cfg, root)]
    equity, trades, scales = mix(sleeves, p.initial_capital)
    traded = 0.0
    for (_, _, r), k in zip(sleeves, scales):
        s = r.metrics["strategy"]
        curve = r.equity.filter(pl.col("date").is_between(period.start, period.end))
        traded += k * s["annual_turnover_x"] * curve["equity"].mean() * s["years"]  # undo the sleeve's normalisation
    extra = {
        "sleeves": {name: {"weight": w, "config": s.config, **{k: r.metrics["strategy"][k] for k in ("cagr_pct", "max_dd_pct", "calmar")}}
                    for (name, w, r), s in zip(sleeves, p.sleeves)},
        "sleeve_daily_return_corr": _daily_return_corr(sleeves, period.start, period.end),
    }
    return score(cfg, root, equity, trades, exposure_metrics(equity, traded, period.start, period.end), extra)
