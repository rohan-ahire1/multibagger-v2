"""Per-(symbol, date) inputs for the VCP scan: universe, trend template, RS rank, volume average, market filter.

Ratios and averages use the adjusted columns; the price floor and ₹ turnover use the raw ones. Every column describes the
close of its own row; the scan reads the day before the breakout through `candidate`.
"""
from __future__ import annotations

import polars as pl

from mb.strategy.vcp.params import Params


def _sma(col: str, window: int) -> pl.Expr:
    return pl.col(col).rolling_mean(window_size=window, min_samples=window).over("symbol")


def _trend_price_rules(tt) -> list[pl.Expr]:
    """Trend template rules 1-5: price and moving-average order, slow average rising."""
    return [
        pl.col("close") > pl.col("sma_mid"),
        pl.col("close") > pl.col("sma_slow"),
        pl.col("sma_mid") > pl.col("sma_slow"),
        pl.col("sma_slow") > pl.col("sma_slow").shift(tt.sma_slow_rising_sessions).over("symbol"),
        pl.col("sma_fast") > pl.col("sma_mid"),
        pl.col("sma_fast") > pl.col("sma_slow"),
        pl.col("close") > pl.col("sma_fast"),
    ]


def features(panel: pl.DataFrame, p: Params) -> pl.DataFrame:
    """Sorted by symbol, date. `panel` must already end at the last allowed date."""
    u, tt, rs = p.universe, p.trend, p.rs
    if len(rs.lookbacks) != len(rs.weights):
        raise ValueError("rs.lookbacks and rs.weights must have the same length")
    f = (
        panel.select("date", "symbol", "series",
                     pl.col("adj_open").alias("open"), pl.col("adj_high").alias("high"), pl.col("adj_low").alias("low"),
                     pl.col("adj_close").alias("close"), pl.col("adj_volume").cast(pl.Float64).alias("volume"),
                     pl.col("close").alias("raw_close"),
                     pl.coalesce(pl.col("turnover"), pl.col("close") * pl.col("volume")).alias("traded_value"))
        .sort("symbol", "date")
        .with_columns(
            pl.col("close").cum_count().over("symbol").alias("history"),
            _sma("close", tt.sma_fast).alias("sma_fast"),
            _sma("close", tt.sma_mid).alias("sma_mid"),
            _sma("close", tt.sma_slow).alias("sma_slow"),
            pl.col("high").rolling_max(window_size=tt.range_sessions, min_samples=tt.range_sessions).over("symbol").alias("high52"),
            pl.col("low").rolling_min(window_size=tt.range_sessions, min_samples=tt.range_sessions).over("symbol").alias("low52"),
            _sma("traded_value", u.adv_window_sessions).alias("adv"),
            pl.col("volume").shift(1).rolling_mean(window_size=p.volume.avg_sessions, min_samples=p.volume.avg_sessions)
            .over("symbol").alias("vol_avg"),
            pl.sum_horizontal([pl.lit(w) * (pl.col("close") / pl.col("close").shift(lb) - 1.0).over("symbol")
                               for lb, w in zip(rs.lookbacks, rs.weights, strict=True)]).alias("rs_score"),
        )
        .with_columns(
            (pl.col("series").is_in(u.allowed_series) & (pl.col("raw_close") >= u.min_price_inr)
             & (pl.col("adv") >= u.min_adv_inr) & (pl.col("history") >= u.min_history_sessions)
             & (pl.col("symbol") != p.market.benchmark_symbol)).fill_null(False).alias("eligible"),
        )
    )
    # rs_score is null until the longest lookback is available; such rows cannot be ranked.
    rankable = pl.col("eligible") & pl.col("rs_score").is_not_null()
    f = f.with_columns(
        pl.when(rankable).then(pl.col("rs_score")).otherwise(None).rank("average").over("date").alias("_rank"),
        rankable.cast(pl.Int64).sum().over("date").alias("_n"),
    ).with_columns(
        pl.when(~rankable).then(None)
        .when(pl.col("_n") == 1).then(100.0)
        .otherwise((pl.col("_rank") - 1.0) / (pl.col("_n") - 1).cast(pl.Float64) * 100.0).alias("rs_rank"),
    ).drop("_rank", "_n")
    f = f.with_columns(
        pl.all_horizontal(
            *_trend_price_rules(tt),
            pl.col("close") >= pl.col("low52") * (1.0 + tt.min_above_low_pct),
            pl.col("close") >= pl.col("high52") * (1.0 - tt.max_below_high_pct),
            pl.col("rs_rank") >= tt.min_rs_rank,
        ).fill_null(False).alias("trend_ok"),
    )
    market = (f.filter(pl.col("symbol") == p.market.benchmark_symbol)
              .select("date", pl.all_horizontal(*_trend_price_rules(tt)).fill_null(False).alias("market_ok")))
    if market.is_empty():
        raise ValueError(f"benchmark {p.market.benchmark_symbol} is not in the panel")
    f = f.join(market, on="date", how="left").with_columns(pl.col("market_ok").fill_null(False)).sort("symbol", "date")
    prev = lambda c: pl.col(c).shift(1).over("symbol").fill_null(False)  # noqa: E731
    return f.with_columns(
        (prev("eligible") & prev("trend_ok")).alias("candidate"),
        prev("market_ok").alias("market_ok_prev"),
    )
