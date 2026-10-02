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
from mb.strategy.momentum.params import Params, ParamsM8, ParamsM10, ParamsM11, ParamsM12, ParamsM13, ParamsM19, ParamsM21, ParamsM22, ParamsM27, ParamsM29, ParamsM32, ParamsM40, ParamsM44, ParamsM46, ParamsM53, ParamsM55, ParamsM57, ParamsM75, ParamsM76, ParamsM79, ParamsM81, ParamsM82, ParamsM89, ParamsM97, ParamsM99, ParamsM103, UniverseM40
from mb.strategy.momentum.targets import rotation_shares, targets, vol_state_scales, with_book_scale, with_rotation

__all__ = ["Params", "ParamsM8", "ParamsM10", "ParamsM11", "ParamsM12", "ParamsM13", "ParamsM19", "ParamsM21", "ParamsM22", "ParamsM27", "ParamsM29", "ParamsM32", "ParamsM40", "ParamsM44", "ParamsM46", "ParamsM53", "ParamsM55", "ParamsM57", "ParamsM75", "ParamsM76", "ParamsM79", "ParamsM81", "ParamsM82", "ParamsM89", "ParamsM97", "ParamsM99", "ParamsM103", "run", "simulate"]


def simulate(cfg: Resolved, root: Path) -> RebalanceResult:
    """The panel is cut at period.end, so later data cannot leak in. A target on the last session is never traded."""
    p = cfg.params
    assert isinstance(p, Params)
    period = cfg.strategy.period
    panel = (pl.scan_parquet(datasets.dataset_path(root, cfg.strategy.dataset) / datasets.PANEL_FILE)
             .filter(pl.col("date") <= period.end)
             .select("date", "symbol", "security_id", "series", "close", "turnover", "adj_open", "adj_high", "adj_close",
                     *(("volume", "deliv_qty") if isinstance(p.universe, UniverseM40)
                       and p.universe.delivery_drop_frac is not None else ()))
             .collect())
    days = sorted(panel.filter(pl.col("date").is_between(period.start, period.end))["date"].unique().to_list())
    bars = panel.select("date", "symbol", pl.col("adj_open").alias("open"), pl.col("adj_close").alias("close"))
    sectors = load_sectors(root, cfg)
    # Which symbols are fund units is a fact about the listing, not a price: read it from the whole dataset, since
    # bhavcopies before mid-2011 carry no ISIN (M35).
    funds = frozenset(pl.scan_parquet(datasets.dataset_path(root, cfg.strategy.dataset) / datasets.PANEL_FILE)
                      .filter(pl.col("security_id").str.starts_with("isin:INF")).select("symbol").unique()
                      .collect()["symbol"].to_list())
    tg = targets(panel, p, period.start, period.end, sectors=sectors, days_per_year=cfg.market.trading_days_per_year,
                 fund_symbols=funds)
    stop = p.exits.stop_loss_frac if isinstance(p, ParamsM11) else None
    stop_to = p.exits.stop_proceeds_to if isinstance(p, ParamsM75) else None
    trail = p.exits.stop_trailing if isinstance(p, ParamsM76) else False
    svol = ((p.exits.stop_vol_sessions, p.exits.stop_vol_mult)
            if isinstance(p, ParamsM76) and p.exits.stop_vol_sessions is not None else None)
    smkt = ((p.exits.stop_market_symbol, p.exits.stop_market_frac)
            if isinstance(p, ParamsM79) and p.exits.stop_market_symbol is not None else None)
    respread = isinstance(p, ParamsM81) and p.exits.stop_respread
    reentry = isinstance(p, ParamsM82) and p.exits.stop_reentry
    if isinstance(p, ParamsM27) and p.portfolio.rotation is not None:
        # M27: the shadow book is the same strategy from the panel's first session; its equity is the book's record.
        all_days = sorted(panel["date"].unique().to_list())
        shadow_tg = targets(panel, p, all_days[0], period.end, sectors=sectors, days_per_year=cfg.market.trading_days_per_year,
                            fund_symbols=funds)
        shadow = simulate_targets(shadow_tg, bars, all_days, cfg.market, p.initial_capital, stop, stop_to, trail, svol, smkt, respread, reentry).equity
        share = rotation_shares(shadow.select("date", "equity"), panel, p.portfolio.rotation, sorted(tg))
        tg = {d: with_rotation(t, share[d]) for d, t in tg.items()}
    if isinstance(p, ParamsM32) and p.portfolio.vol_states is not None:
        # M32: the shadow book is this strategy without fixed weights or scaling, from the panel's first session.
        all_days = sorted(panel["date"].unique().to_list())
        bare = p.model_copy(update={"portfolio": p.portfolio.model_copy(update={"fixed_weights": {}, "vol_states": None})})
        shadow_tg = targets(panel, bare, all_days[0], period.end, sectors=sectors,
                            days_per_year=cfg.market.trading_days_per_year, fund_symbols=funds)
        shadow = simulate_targets(shadow_tg, bars, all_days, cfg.market, p.initial_capital, stop, stop_to, trail, svol, smkt, respread, reentry).equity
        k = vol_state_scales(shadow.select("date", "equity"), shadow_tg, p.portfolio.vol_states, sorted(tg))
        tg = {d: with_book_scale(t, k[d], set(p.portfolio.fixed_weights)) for d, t in tg.items()}
    return simulate_targets(tg, bars, days, cfg.market, p.initial_capital, stop, stop_to, trail, svol, smkt, respread, reentry)


def run(cfg: Resolved, root: Path) -> RunResult:
    period = cfg.strategy.period
    res = simulate(cfg, root)
    fills = res.fills.filter(pl.col("date").is_between(period.start, period.end))
    traded = (fills["shares"] * fills["price"]).sum() if fills.height else 0.0
    exposure = exposure_metrics(res.equity, traded, period.start, period.end)
    return score(cfg, root, res.equity, res.holdings, exposure, {"rebalances": res.rebalances})
