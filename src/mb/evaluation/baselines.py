"""The two yardsticks every run is shown beside: Nifty 500 TRI buy-and-hold and plain 12-1 momentum.

Both are measured with the same equity-curve metrics as the strategy, over the same period, and the momentum baseline pays
the same slippage and charges. Prices come from the dataset panel cut at `end`, so nothing after the period leaks in.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from mb.config.models import BaselinesConfig, MarketConfig, Momentum
from mb.engine.rebalance import Target, simulate_targets
from mb.evaluation.metrics import equity_metrics
from mb.strategy.momentum.params import Ranking, Universe
from mb.strategy.momentum.targets import ranked


def buy_and_hold_curve(root: Path, cfg: BaselinesConfig) -> pl.DataFrame:
    return pl.read_csv(root / cfg.buy_and_hold.tri_file, try_parse_dates=True).rename({"tri": "equity"})


def _rebalance_picks(panel: pl.DataFrame, m: Momentum, start: date, end: date) -> dict[date, list[str]]:
    """Month-end ranking: for each rebalance date, the top_n eligible symbols by plain 12-1 return.

    The baseline is the plain version of the momentum strategy: return score, fund units not excluded, no buffer, no regime.
    """
    universe = Universe(allowed_series=m.allowed_series, min_price_inr=m.min_price_inr, min_adv_inr=m.min_adv_inr,
                        adv_window_sessions=m.adv_window_sessions, exclude_fund_units=False)
    ranking = Ranking(lookback_sessions=m.lookback_sessions, skip_sessions=m.skip_sessions, score="return")
    return {d: order[: m.top_n] for d, order in ranked(panel, universe, ranking, start, end).items()}


def momentum_curve(cfg: BaselinesConfig, market: MarketConfig, panel_path: Path, start: date, end: date) -> tuple[pl.DataFrame, int]:
    """Daily equity of the momentum baseline over [start, end], and the number of rebalances."""
    m = cfg.momentum
    panel = (pl.scan_parquet(panel_path).filter(pl.col("date") <= end)
             .select("date", "symbol", "series", "close", "turnover", "adj_open", "adj_close").collect())
    picks = _rebalance_picks(panel, m, start, end)
    days = sorted(panel.filter(pl.col("date").is_between(start, end))["date"].unique().to_list())
    bars = panel.select("date", "symbol", pl.col("adj_open").alias("open"), pl.col("adj_close").alias("close"))
    res = simulate_targets({d: Target({s: 1.0 for s in names}, 1.0) for d, names in picks.items()}, bars, days, market,
                           m.initial_capital)
    return res.equity, res.rebalances


def _covers(curve: pl.DataFrame, start: date) -> bool:
    """The TRI file starts 2010-01-04; a window starting before it has no TRI figures (the adoption check reads None)."""
    return curve["date"].min() <= start


def compute(root: Path, cfg: BaselinesConfig, market: MarketConfig, panel_path: Path, start: date, end: date) -> dict[str, Any]:
    """Both baselines over the run's period and over each development fold inside it.

    Each baseline runs once over the period; a fold is a slice of that one curve, the same way the strategy's folds are.
    """
    tri = buy_and_hold_curve(root, cfg)
    mom, rebalances = momentum_curve(cfg, market, panel_path, start, end)
    windows = {"period": (start, end)} | {f.name: (f.start, f.end) for f in cfg.folds if f.start >= start and f.end <= end}
    out: dict[str, Any] = {}
    for label, curve in (("nifty500_tri_buy_and_hold", tri), ("momentum_12_1", mom)):
        out[label] = {w: equity_metrics(curve, s, e) if _covers(curve, s) else {} for w, (s, e) in windows.items()}
    out["momentum_12_1"]["period"]["rebalances"] = rebalances
    out["momentum_12_1"]["period"]["avg_open_positions"] = mom.filter(pl.col("date").is_between(start, end))["open_positions"].mean()
    return out
