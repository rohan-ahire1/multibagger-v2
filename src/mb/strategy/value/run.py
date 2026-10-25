"""M144 value book: point-in-time earnings yield from NSE quarterly results -> monthly targets -> rebalance simulator."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from mb.config.loader import Resolved
from mb.data import datasets, fundamentals
from mb.engine.rebalance import RebalanceResult, Target, simulate_targets
from mb.engine.run import score
from mb.evaluation.metrics import exposure_metrics
from mb.runs.record import RunResult
from mb.sources import nse_results
from mb.strategy.momentum.targets import decision_dates
from mb.strategy.value.params import Params

__all__ = ["Params", "run", "targets", "simulate"]


def targets(panel: pl.DataFrame, filings: pl.DataFrame, p: Params, start: date, end: date,
            funds: frozenset[str]) -> dict[date, Target]:
    u = p.universe
    dec = decision_dates(panel, start, end, p.decision_offset_sessions)
    elig = (panel.filter(pl.col("series").is_in(u.allowed_series)).sort("symbol", "date")
            .with_columns(pl.col("turnover").rolling_mean(u.adv_window_sessions, min_samples=u.adv_window_sessions)
                          .over("symbol").alias("adv"))
            .filter(pl.col("date").is_in(dec) & (pl.col("close") >= u.min_price_inr) & (pl.col("adv") >= u.min_adv_inr)))
    if u.exclude_fund_units:
        elig = elig.filter(~pl.col("symbol").is_in(list(funds)))
    ok = {d: set(g["symbol"].to_list()) for (d,), g in elig.group_by("date")}
    ttm = fundamentals.ttm_profit(filings, dec, p.max_age_days)
    caps = fundamentals.market_caps(filings, panel, dec, p.max_age_days)
    out: dict[date, Target] = {}
    for d in dec:
        ey = {s: ttm[d][s] / caps[d][s] for s in ok.get(d, set()) if s in ttm[d] and s in caps[d] and ttm[d][s] > 0.0}
        pick = sorted(ey, key=lambda s: (-ey[s], s))[: p.top_n]
        out[d] = Target({s: 1.0 for s in pick}, 1.0 if pick else 0.0)
    return out


def simulate(cfg: Resolved, root: Path) -> RebalanceResult:
    p = cfg.params
    assert isinstance(p, Params)
    period = cfg.strategy.period
    path = datasets.dataset_path(root, cfg.strategy.dataset) / datasets.PANEL_FILE
    panel = (pl.scan_parquet(path).filter(pl.col("date") <= period.end)
             .select("date", "symbol", "security_id", "series", "close", "turnover", "adj_open", "adj_close", "adj_factor")
             .collect())
    funds = frozenset(pl.scan_parquet(path).filter(pl.col("security_id").str.starts_with("isin:INF")).select("symbol")
                      .unique().collect()["symbol"].to_list())
    tg = targets(panel, nse_results.load(root / p.results_raw_dir), p, period.start, period.end, funds)
    days = sorted(panel.filter(pl.col("date").is_between(period.start, period.end))["date"].unique().to_list())
    bars = panel.select("date", "symbol", pl.col("adj_open").alias("open"), pl.col("adj_close").alias("close"))
    return simulate_targets(tg, bars, days, cfg.market, p.initial_capital)


def run(cfg: Resolved, root: Path) -> RunResult:
    period = cfg.strategy.period
    res = simulate(cfg, root)
    fills = res.fills.filter(pl.col("date").is_between(period.start, period.end))
    traded = (fills["shares"] * fills["price"]).sum() if fills.height else 0.0
    exposure = exposure_metrics(res.equity, traded, period.start, period.end)
    return score(cfg, root, res.equity, res.holdings, exposure, {"rebalances": res.rebalances})
