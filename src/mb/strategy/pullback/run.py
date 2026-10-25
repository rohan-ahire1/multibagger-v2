"""Pullback strategy (M108, docs/research/m108.md): buy a stock in an uptrend after a short-term washout, sell when it
closes back above its short average. Panel -> features -> signals -> engine -> metrics."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from mb.config.loader import Resolved
from mb.data import datasets
from mb.engine.run import evaluate, load_bars
from mb.runs.record import RunResult
from mb.strategy.pullback.params import (Params, ParamsM109, ParamsM110, ParamsM112, RelativeStrengthM112, SetupM109,
                                         SetupM110)

__all__ = ["Params", "ParamsM109", "ParamsM110", "ParamsM112", "run", "features", "signals"]


def _rsi(n: int) -> pl.Expr:
    """Wilder RSI of adj close: averages of gains and losses with alpha 1/n."""
    d = pl.col("close").diff()
    up = d.clip(lower_bound=0.0).ewm_mean(alpha=1.0 / n, adjust=False, min_samples=n).over("symbol")
    dn = (-d).clip(lower_bound=0.0).ewm_mean(alpha=1.0 / n, adjust=False, min_samples=n).over("symbol")
    return pl.when(dn == 0.0).then(100.0).otherwise(100.0 - 100.0 / (1.0 + up / dn))


def features(panel: pl.DataFrame, p: Params) -> pl.DataFrame:
    """Sorted by symbol, date; every column describes the close of its own row. `panel` must end at the last allowed date."""
    u, st, rs = p.universe, p.setup, p.rs
    if isinstance(rs, RelativeStrengthM112):
        span = rs.lookback_sessions - rs.skip_sessions
        lr = (pl.col("close") / pl.col("close").shift(1)).log()
        rs_score = ((pl.col("close").shift(rs.skip_sessions) / pl.col("close").shift(rs.lookback_sessions) - 1.0)
                    / lr.rolling_std(span, min_samples=span).shift(rs.skip_sessions)).over("symbol")
    else:
        if len(rs.lookbacks) != len(rs.weights):
            raise ValueError("rs.lookbacks and rs.weights must have the same length")
        rs_score = pl.sum_horizontal([pl.lit(w) * (pl.col("close") / pl.col("close").shift(lb) - 1.0).over("symbol")
                                      for lb, w in zip(rs.lookbacks, rs.weights, strict=True)])
    f = (
        panel.select("date", "symbol", "series", "security_id", pl.col("adj_close").alias("close"),
                     pl.col("adj_volume").cast(pl.Float64).alias("volume"),
                     pl.col("close").alias("raw_close"),
                     pl.coalesce(pl.col("turnover"), pl.col("close") * pl.col("volume")).alias("traded_value"))
        .sort("symbol", "date")
        .with_columns(
            pl.col("close").cum_count().over("symbol").alias("history"),
            pl.col("close").rolling_mean(st.trend_sma_sessions, min_samples=st.trend_sma_sessions).over("symbol").alias("sma"),
            pl.col("traded_value").rolling_mean(u.adv_window_sessions, min_samples=u.adv_window_sessions).over("symbol").alias("adv"),
            _rsi(st.rsi_sessions).alias("rsi"),
            rs_score.alias("rs_score"),
        )
    )
    eligible = (pl.col("series").is_in(u.allowed_series) & (pl.col("raw_close") >= u.min_price_inr)
                & (pl.col("adv") >= u.min_adv_inr) & (pl.col("history") >= u.min_history_sessions))
    if u.exclude_fund_units:
        funds = panel.filter(pl.col("security_id").str.starts_with("isin:INF"))["symbol"].unique()
        eligible = eligible & ~pl.col("symbol").is_in(funds.implode())
    f = f.with_columns(eligible.fill_null(False).alias("eligible"))
    rankable = pl.col("eligible") & pl.col("rs_score").is_not_null() & pl.col("rs_score").is_finite()
    f = f.with_columns(
        pl.when(rankable).then(pl.col("rs_score")).otherwise(None).rank("average").over("date").alias("_rank"),
        rankable.cast(pl.Int64).sum().over("date").alias("_n"),
    ).with_columns(
        pl.when(~rankable).then(None)
        .when(pl.col("_n") == 1).then(100.0)
        .otherwise((pl.col("_rank") - 1.0) / (pl.col("_n") - 1).cast(pl.Float64) * 100.0).alias("rs_rank"),
    ).drop("_rank", "_n")
    m = p.market
    market = (panel.filter(pl.col("symbol") == m.benchmark_symbol).sort("date")
              .select("date", (pl.col("adj_close") > pl.col("adj_close").rolling_mean(m.sma_sessions, min_samples=m.sma_sessions))
                      .fill_null(False).alias("market_ok")))
    if market.is_empty():
        raise ValueError(f"benchmark {m.benchmark_symbol} is not in the panel")
    f = f.join(market, on="date", how="left").with_columns(pl.col("market_ok").fill_null(False))
    setup = (pl.col("eligible") & (pl.col("close") > pl.col("sma")) & (pl.col("rsi") <= st.rsi_max))
    if st.min_rs_rank > 0.0:
        setup = setup & (pl.col("rs_rank") >= st.min_rs_rank)
    if m.enabled:
        setup = setup & pl.col("market_ok")
    if isinstance(st, SetupM110):
        n = st.volume_avg_sessions
        avg = pl.col("volume").shift(2).rolling_mean(n, min_samples=n).over("symbol")
        recent = pl.max_horizontal(pl.col("volume"), pl.col("volume").shift(1).over("symbol"))
        setup = setup & (recent <= st.max_volume_to_avg * avg)
    return f.with_columns(setup.fill_null(False).alias("setup")).sort("symbol", "date")


def _order(st) -> list:
    """Sort keys for a day's signals: date first, then the rank rule, then symbol."""
    rs = pl.col("rs_score").fill_null(-1e9)
    if isinstance(st, SetupM109) and st.rank_by == "rs":
        return [pl.col("date"), rs.neg(), pl.col("rsi"), pl.col("symbol")]
    return [pl.col("date"), pl.col("rsi"), rs.neg(), pl.col("symbol")]


def signals(f: pl.DataFrame, p: Params, start, end) -> pl.DataFrame:
    """One signal per setup day in the period, ranked within the day by lowest RSI, then higher RS score."""
    sg = p.signal
    if p.engine.entry.order == "open" and sg.limit_below_close_pct != 0.0:
        raise ValueError("an `open` entry takes no limit offset")
    return (f.filter(pl.col("setup") & pl.col("date").is_between(start, end))
            .sort(*_order(p.setup))
            .with_columns(pl.int_range(pl.len()).over("date").alias("rank"))
            .select("symbol", pl.col("date").alias("signal_date"),
                    (pl.col("close") * (1.0 - sg.limit_below_close_pct)).alias("entry_ref"),
                    (pl.col("close") * (1.0 - sg.limit_below_close_pct) * (1.0 - sg.stop_below_ref_pct)).alias("stop"),
                    pl.lit(1.0).alias("size_mult"), "rank", "rsi", "rs_rank"))


def run(cfg: Resolved, root: Path) -> RunResult:
    p = cfg.params
    assert isinstance(p, Params)
    period = cfg.strategy.period
    panel = (pl.scan_parquet(datasets.dataset_path(root, cfg.strategy.dataset) / datasets.PANEL_FILE)
             .filter(pl.col("date") <= period.end).collect())
    sigs = signals(features(panel, p), p, period.start, period.end)
    _, result = evaluate(cfg, root, p.engine, sigs, load_bars(root, cfg, p.engine))
    return result
