"""Momentum strategy runner: panel -> month-end targets -> rebalance simulator -> metrics."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from mb.config.loader import Resolved
from mb.data import datasets
from mb.engine.rebalance import RebalanceResult, simulate_targets
from mb.engine.run import load_sectors, score
from mb.evaluation.metrics import exposure_metrics
from mb.runs.record import RunResult
from mb.strategy.momentum.params import Params, ParamsM8, ParamsM10, ParamsM11, ParamsM12, ParamsM13, ParamsM19, ParamsM21, ParamsM22, ParamsM27, ParamsM29
from mb.strategy.momentum.targets import rotation_shares, targets, with_rotation

__all__ = ["Params", "ParamsM8", "ParamsM10", "ParamsM11", "ParamsM12", "ParamsM13", "ParamsM19", "ParamsM21", "ParamsM22", "ParamsM27", "ParamsM29", "run", "simulate"]


def simulate(cfg: Resolved, root: Path) -> RebalanceResult:
    """The panel is cut at period.end, so later data cannot leak in. A target on the last session is never traded."""
    p = cfg.params
    assert isinstance(p, Params)
    period = cfg.strategy.period
    panel = (pl.scan_parquet(datasets.dataset_path(root, cfg.strategy.dataset) / datasets.PANEL_FILE)
             .filter(pl.col("date") <= period.end)
             .select("date", "symbol", "security_id", "series", "close", "turnover", "adj_open", "adj_high", "adj_close")
             .collect())
    days = sorted(panel.filter(pl.col("date").is_between(period.start, period.end))["date"].unique().to_list())
    bars = panel.select("date", "symbol", pl.col("adj_open").alias("open"), pl.col("adj_close").alias("close"))
    sectors = load_sectors(root, cfg)
    tg = targets(panel, p, period.start, period.end, sectors=sectors, days_per_year=cfg.market.trading_days_per_year)
    stop = p.exits.stop_loss_frac if isinstance(p, ParamsM11) else None
    if isinstance(p, ParamsM27) and p.portfolio.rotation is not None:
        # M27: the shadow book is the same strategy from the panel's first session; its equity is the book's record.
        all_days = sorted(panel["date"].unique().to_list())
        shadow_tg = targets(panel, p, all_days[0], period.end, sectors=sectors, days_per_year=cfg.market.trading_days_per_year)
        shadow = simulate_targets(shadow_tg, bars, all_days, cfg.market, p.initial_capital, stop).equity
        share = rotation_shares(shadow.select("date", "equity"), panel, p.portfolio.rotation, sorted(tg))
        tg = {d: with_rotation(t, share[d]) for d, t in tg.items()}
    return simulate_targets(tg, bars, days, cfg.market, p.initial_capital, stop)


def run(cfg: Resolved, root: Path) -> RunResult:
    period = cfg.strategy.period
    res = simulate(cfg, root)
    fills = res.fills.filter(pl.col("date").is_between(period.start, period.end))
    traded = (fills["shares"] * fills["price"]).sum() if fills.height else 0.0
    exposure = exposure_metrics(res.equity, traded, period.start, period.end)
    return score(cfg, root, res.equity, res.holdings, exposure, {"rebalances": res.rebalances})
