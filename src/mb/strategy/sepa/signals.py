"""SEPA breakout signals, computed for every (symbol, date) at once.

Ported from v1's scan (`signal_engine`, `trend_template`, `vcp_setup`, `indicators/*`) and its signal filter
(`filter_signals`), BREAKOUT branch only, ranking mode "default". Indicators use the adjusted columns; absolute levels use
the raw close and raw turnover.
"""
from __future__ import annotations

from datetime import date

import polars as pl

from mb.strategy.sepa.contraction import contraction_counts
from mb.strategy.sepa.params import Params

SIGNAL_COLUMNS = ["symbol", "signal_date", "entry_ref", "stop", "size_mult", "pivot", "rs_rank", "range10", "voldry",
                  "vol_mult", "atr_pct", "adv50", "contraction_count"]


def _sma(col: str, window: int) -> pl.Expr:
    return pl.col(col).rolling_mean(window_size=window, min_samples=window).over("symbol")


def _base_columns(panel: pl.DataFrame, p: Params) -> pl.DataFrame:
    """Indicators that do not depend on the contraction count."""
    tt, st = p.trend, p.setup
    f = (
        panel.select("date", "symbol", "series",
                     pl.col("adj_high").alias("high"), pl.col("adj_low").alias("low"),
                     pl.col("adj_close").alias("close"), pl.col("adj_volume").alias("volume"),
                     pl.col("turnover"), pl.col("close").alias("raw_close"))
        .sort("symbol", "date")
        .with_columns(
            pl.col("close").cum_count().over("symbol").alias("history_count"),
            pl.coalesce(pl.col("turnover"), pl.col("close") * pl.col("volume")).alias("traded_value"),
        )
    )
    prev_close = pl.col("close").shift(1).over("symbol")
    f = f.with_columns(
        _sma("close", tt.sma_fast).alias("sma50"),
        _sma("close", tt.sma_mid).alias("sma150"),
        _sma("close", tt.sma_slow).alias("sma200"),
        pl.col("high").rolling_max(window_size=tt.lookback_52w, min_samples=tt.lookback_52w).over("symbol").alias("high52"),
        pl.col("low").rolling_min(window_size=tt.lookback_52w, min_samples=tt.lookback_52w).over("symbol").alias("low52"),
        _sma("volume", 10).alias("vol10"),
        _sma("volume", 50).alias("vol50"),
        _sma("traded_value", 50).alias("adv50"),
        ((pl.col("high").rolling_max(window_size=10, min_samples=10).over("symbol")
          - pl.col("low").rolling_min(window_size=10, min_samples=10).over("symbol")) / pl.col("close")).alias("range10"),
        pl.col("high").rolling_max(window_size=st.base_lookback, min_samples=st.base_lookback).over("symbol").alias("base_high"),
        pl.col("low").rolling_min(window_size=st.base_lookback, min_samples=st.base_lookback).over("symbol").alias("base_low"),
        pl.col("high").rolling_max(window_size=st.base_lookback, min_samples=st.base_lookback).shift(1).over("symbol").alias("pivot"),
        pl.max_horizontal(pl.col("high") - pl.col("low"), (pl.col("high") - prev_close).abs(),
                          (pl.col("low") - prev_close).abs()).alias("_tr"),
        prev_close.alias("prev_close"),
    ).with_columns(
        pl.col("sma200").shift(tt.sma200_slope_lookback).over("symbol").alias("sma200_lag"),
        (pl.col("vol10") / pl.col("vol50")).alias("voldry"),
        ((pl.col("base_high") - pl.col("base_low")) / pl.col("base_high")).alias("base_depth"),
        (pl.col("volume") / pl.col("vol50")).alias("vol_mult"),
        pl.col("_tr").ewm_mean(alpha=1.0 / st.atr_period, adjust=False, min_samples=st.atr_period).over("symbol").alias("atr"),
    ).with_columns(
        (pl.col("atr") / pl.col("close")).alias("atr_pct"),
    ).with_columns(
        _sma("atr_pct", 10).alias("atr_pct_sma10"),
        _sma("atr_pct", 20).alias("atr_pct_sma20"),
        _sma("atr_pct", 30).alias("atr_pct_sma30"),
        pl.col("atr_pct").shift(1).over("symbol").alias("atr_pct_prev"),
        pl.col("range10").shift(1).over("symbol").alias("range10_prev"),
        pl.col("voldry").shift(1).over("symbol").alias("voldry_prev"),
    ).drop("_tr")
    return f.with_columns(
        pl.all_horizontal(
            pl.col("close") > pl.col("sma150"),
            pl.col("close") > pl.col("sma200"),
            pl.col("sma150") > pl.col("sma200"),
            pl.col("sma200") > pl.col("sma200_lag"),
            pl.col("sma50") > pl.col("sma150"),
            pl.col("sma50") > pl.col("sma200"),
            pl.col("close") > pl.col("sma50"),
            pl.col("close") >= pl.col("low52") * (1.0 + tt.min_above_52w_low_pct),
            pl.col("close") >= pl.col("high52") * (1.0 - tt.max_below_52w_high_pct),
        ).alias("trend_pass"),
        pl.all_horizontal(
            pl.col("range10") <= st.max_range10_pct,
            pl.col("voldry") <= st.max_vol_dryup_ratio,
            pl.col("atr_pct_sma10") < pl.col("atr_pct_sma20"),
            pl.col("atr_pct_sma10") / pl.col("atr_pct_sma30") <= st.atr_contraction_factor,
            pl.col("close") <= pl.col("sma50") * (1.0 + st.max_extension_from_50sma_pct),
            pl.col("base_depth") <= st.base_max_depth_pct,
        ).alias("setup_core"),
    )


def features(panel: pl.DataFrame, p: Params) -> pl.DataFrame:
    """All per-row features the signal rule needs. `panel` must already end at the last allowed date."""
    f = _base_columns(panel, p)
    # The contraction count only matters where the rest of the setup passes on the day or the day before.
    wanted = f.select((pl.col("setup_core").fill_null(False)
                       | pl.col("setup_core").shift(1).over("symbol").fill_null(False)).alias("w"))["w"]
    f = f.with_columns(contraction_counts(f, wanted, p.setup.base_lookback, p.setup.contraction_smooth_window,
                                          p.setup.contraction_min_peak_pct))
    f = f.with_columns(
        (pl.col("setup_core") & (pl.col("contraction_count") <= p.setup.contraction_max_count)).alias("setup_pass"),
    ).with_columns(
        pl.col("setup_pass").shift(1).over("symbol").alias("setup_pass_prev"),
        (~pl.col("setup_pass").fill_null(False)).cum_sum().over("symbol").alias("_group"),
    ).with_columns(
        pl.col("setup_pass").fill_null(False).cast(pl.Int32).cum_sum().over("symbol", "_group").alias("setup_streak"),
    ).drop("_group")
    return f.with_columns(_rs_rank(f, p))


def _rs_rank(f: pl.DataFrame, p: Params) -> pl.Series:
    """Percentile rank (0..100) of the relative-strength score among that day's eligible symbols; null if not eligible."""
    u, rs = p.universe, p.rs
    if len(rs.lookbacks) != len(rs.weights):
        raise ValueError("rs.lookbacks and rs.weights must have the same length")
    skip = rs.skip_recent_days
    rets, terms = [], []
    for lb, w in zip(rs.lookbacks, rs.weights, strict=True):
        cur = pl.col("close").shift(skip) if skip > 0 else pl.col("close")
        rets.append(((cur / pl.col("close").shift(lb + skip)) - 1.0).over("symbol").alias(f"ret_{lb}"))
        terms.append(pl.lit(w) * ((1.0 + pl.col(f"ret_{lb}")) / (1.0 + pl.col(f"bm_ret_{lb}")) - 1.0))
    with_ret = f.select("date", "symbol", "close").with_columns(rets)
    bench = with_ret.filter(pl.col("symbol") == u.benchmark_symbol).select(
        "date", *[pl.col(f"ret_{lb}").alias(f"bm_ret_{lb}") for lb in rs.lookbacks])
    score = (with_ret.join(bench, on="date", how="left", maintain_order="left")
             .select(pl.sum_horizontal(terms).alias("rs_score")))["rs_score"]

    eligible = (
        (f["history_count"] >= u.min_history_days)
        & (f["raw_close"] >= u.min_price_inr)
        & (f["adv50"] >= u.min_adv50_inr)
        & (f["vol50"] >= u.min_avg_volume_shares)
        & (f["symbol"] != u.benchmark_symbol)
        & f["series"].is_in(u.allowed_series)
    ).fill_null(False)
    d = pl.DataFrame({"date": f["date"], "eligible": eligible, "adv50": f["adv50"], "rs_score": score})
    d = d.with_columns(
        pl.when(pl.col("eligible")).then(pl.col("adv50")).otherwise(None).rank("ordinal", descending=True)
        .over("date").alias("_liq_rank"),
    ).with_columns(
        (pl.col("eligible") & (pl.col("_liq_rank") <= u.max_symbols)).alias("candidate"),
    ).with_columns(
        pl.when(pl.col("candidate")).then(pl.col("rs_score")).otherwise(None).rank("average").over("date").alias("_rank"),
        pl.col("candidate").cast(pl.Int64).sum().over("date").alias("_n"),
    )
    rank = (
        pl.when(~pl.col("candidate")).then(None)
        .when(pl.col("_n") == 1).then(100.0)
        .otherwise((pl.col("_rank") - 1.0) / (pl.col("_n") - 1).cast(pl.Float64) * 100.0)
    )
    return d.select(rank.alias("rs_rank"))["rs_rank"]


def breakout_signals(f: pl.DataFrame, p: Params, start: date, end: date) -> pl.DataFrame:
    """Signals dated in [start, end]: the breakout rule, then the quality filters, then the daily cap."""
    b, r, sel = p.breakout, p.risk, p.selection
    level = pl.col("pivot") * (1.0 + pl.col("atr_pct_prev").fill_null(0.0) * b.buffer_atr_mult)
    entry_ref = pl.col("pivot") * (1.0 + pl.col("atr_pct_prev").fill_null(0.0) * r.entry_buffer_atr_mult)
    struct_prev = entry_ref - pl.col("atr_pct_prev") * pl.col("prev_close") * r.struct_stop_atr_mult
    max_loss = entry_ref * (1.0 - r.max_stop_pct)

    c = f.filter(pl.col("date").is_between(start, end)).with_columns(
        level.alias("_level"), entry_ref.alias("entry_ref"),
    ).with_columns(
        pl.max_horizontal(struct_prev, max_loss).alias("stop"),
    )
    c = c.filter(
        pl.col("trend_pass")
        & (pl.col("rs_rank") >= p.rs.rank_min) & (pl.col("rs_rank") <= p.rs.rank_max)
        & pl.col("setup_pass_prev").fill_null(False)
        & (pl.col("close") >= pl.col("_level"))
        & (pl.col("volume") >= pl.col("vol50") * b.vol_mult)
        & (pl.col("volume") <= pl.col("vol50") * b.vol_max_mult)
        & (pl.col("prev_close") < pl.col("_level"))
        & (pl.col("close") <= pl.col("sma50") * (1.0 + b.max_extension_breakout_pct))
        & (pl.col("contraction_count") <= p.setup.contraction_max_count)
        & (pl.col("entry_ref") - pl.col("stop") > 0)
        & ~pl.col("date").dt.month().is_in(sel.skip_months)
        & (pl.col("range10_prev") <= sel.range10_max)
        & (pl.col("voldry_prev") <= sel.voldry_max)
        & (pl.col("contraction_count") <= sel.contraction_max)
        & (pl.col("setup_streak") <= sel.setup_streak_max)
    )
    c = (
        c.select(pl.col("date").alias("signal_date"), "symbol", "entry_ref", "stop", "pivot", "rs_rank",
                 pl.col("range10_prev").alias("range10"), pl.col("voldry_prev").alias("voldry"), "vol_mult",
                 pl.col("atr_pct_prev").alias("atr_pct"), "adv50", "contraction_count")
        .sort("signal_date", "symbol")
        .sort(["signal_date", "rs_rank", "vol_mult", "range10", "symbol"],
              descending=[False, True, True, False, False], maintain_order=True)
        .group_by("signal_date", maintain_order=True).head(sel.max_signals_per_day)
    )
    return c.with_columns(pl.lit(1.0).alias("size_mult")).select(SIGNAL_COLUMNS)
