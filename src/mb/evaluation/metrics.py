"""The one metrics module. CAGR and drawdown come from the daily equity curve, never from trade R."""
from __future__ import annotations

import math
from datetime import date
from typing import Any

import polars as pl

DAYS_PER_YEAR = 365.25
MIN_CURVE_ROWS = 20


def _window(equity: pl.DataFrame, start: date, end: date) -> pl.DataFrame:
    curve = equity.filter(pl.col("date").is_between(start, end)).sort("date")
    if curve.height < MIN_CURVE_ROWS:
        raise ValueError(f"equity curve has {curve.height} rows in {start}..{end}; need at least {MIN_CURVE_ROWS}")
    return curve


def equity_metrics(equity: pl.DataFrame, start: date, end: date) -> dict[str, Any]:
    """CAGR, max drawdown and Calmar over [start, end]. CAGR is measured from the first equity value in the window."""
    curve = _window(equity, start, end)
    values = curve["equity"].to_list()
    first, last = curve["date"][0], curve["date"][-1]
    years = max((last - first).days / DAYS_PER_YEAR, 1e-6)
    cagr = (values[-1] / values[0]) ** (1.0 / years) - 1.0
    peak, worst = -math.inf, 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return {
        "first_date": first.isoformat(), "last_date": last.isoformat(), "years": years,
        "start_equity": values[0], "end_equity": values[-1],
        "cagr_pct": cagr * 100.0, "max_dd_pct": abs(worst) * 100.0,
        "calmar": cagr / abs(worst) if worst < 0.0 else None,
    }


def exposure_metrics(equity: pl.DataFrame, traded: float, start: date, end: date) -> dict[str, Any]:
    """`traded` is the gross value bought plus sold over [start, end]."""
    curve = _window(equity, start, end)
    invested_frac = (pl.col("invested_value") / pl.col("equity")).mean()
    years = max((curve["date"][-1] - curve["date"][0]).days / DAYS_PER_YEAR, 1e-6)
    return {
        "avg_invested_frac": curve.select(invested_frac).item(),
        "avg_open_positions": curve["open_positions"].mean(),
        "annual_turnover_x": traded / curve["equity"].mean() / years,
    }


def traded_value(trades: pl.DataFrame, start: date, end: date) -> float:
    """Entry plus exit value of the engine's trades entered in [start, end]."""
    filled = _filled(trades, start, end)
    return (filled["shares"] * (filled["entry_price"] + filled["exit_price"])).sum() if filled.height else 0.0


def _filled(trades: pl.DataFrame, start: date, end: date) -> pl.DataFrame:
    return trades.filter(pl.col("entry_date").is_not_null() & pl.col("entry_date").is_between(start, end))


def trade_metrics(trades: pl.DataFrame, start: date, end: date) -> dict[str, Any]:
    """Trades counted by entry date inside the window (a trade may exit after `end`)."""
    t = _filled(trades, start, end)
    if t.is_empty():
        return {"trades": 0}
    wins, losses = t.filter(pl.col("pnl") > 0), t.filter(pl.col("pnl") <= 0)
    gross_win, gross_loss = wins["pnl"].sum(), -losses["pnl"].sum()
    total = t["pnl"].sum()
    by_pnl = t.sort("pnl", descending=True)["pnl"]
    top = max(1, math.ceil(0.05 * t.height))
    r = t["r_multiple"].drop_nulls()
    yearly = t.group_by(pl.col("exit_date").dt.year().alias("year")).agg(pl.col("pnl").sum()).sort("year")
    return {
        "trades": t.height,
        "win_rate_pct": wins.height / t.height * 100.0,
        "avg_r": r.mean(), "median_r": r.median(),
        "r_p10": r.quantile(0.10), "r_p90": r.quantile(0.90), "best_r": r.max(), "worst_r": r.min(),
        "avg_return_pct": t["return_pct"].mean(),
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else None,
        "avg_holding_days": t["holding_days"].mean(),
        "total_pnl": total,
        "top5pct_trades_share_of_pnl": by_pnl.head(top).sum() / total if total > 0 else None,
        "pnl_by_exit_year": {int(y): p for y, p in yearly.iter_rows()},
        "exit_reasons": {k: n for k, n in t.group_by("status").len().sort("status").iter_rows()},
    }
