"""M65 (docs/research/m65.md): square-root market impact at several book sizes, as information (not part of any bar).

Each stock fill pays an extra Y x sigma x sqrt(fill / day's turnover) of its value (Toth et al. 2011; Frazzini, Israel &
Moskowitz 2018), sigma = the stock's daily return volatility over the previous 21 sessions. The fill is sized at a
constant book of S rupees (as in notebooks/m49_capacity.py), so early years, with thinner markets, are charged more.
The drag is taken off each day's return. A blend applies it per sleeve, each sleeve at its weight x S, and mixes the
adjusted sleeve curves at their fixed starting weights (never rebalanced, as the blend strategy does).

Run: uv run python notebooks/m65_impact.py
"""
from __future__ import annotations

import math
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.strategy.momentum.run import simulate

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "strategies/momentum/configs"
Y, VOL_SESSIONS = 1.0, 21
SIZES = (1e6, 5e6, 2e7, 1e8)  # Rs 10 lakh, 50 lakh, 2 crore, 10 crore
BOOKS = {
    "pin m49_b_b2": [("m49_b_b2", 1.0)],
    "top 20 m58_top20_b2": [("m58_top20_b2", 1.0)],
    "top 15 m64_top15_b2": [("m64_top15_b2", 1.0)],
    "half m59_half_b2": [("m49_b_b2", 0.5), ("m59_rot_b2", 0.5)],
    "M61 m61_half_top20_b2": [("m58_top20_b2", 0.5), ("m61_rot_top20_b2", 0.5)],
}

_cache: dict[str, tuple[pl.DataFrame, pl.DataFrame]] = {}


def sleeve(name: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(equity: date, equity; fills: date, symbol, frac = |fill value| / equity, turnover, sigma)."""
    if name not in _cache:
        cfg = load_strategy_config(CFG / f"{name}.yaml", ROOT)
        res = simulate(cfg, ROOT)
        per = cfg.strategy.period
        px = (pl.scan_parquet(datasets.dataset_path(ROOT, cfg.strategy.dataset) / datasets.PANEL_FILE)
              .select("date", "symbol", "turnover", "adj_close").collect().sort("symbol", "date")
              .with_columns((pl.col("adj_close") / pl.col("adj_close").shift(1) - 1).over("symbol").alias("r"))
              .with_columns(pl.col("r").rolling_std(VOL_SESSIONS).shift(1).over("symbol").alias("sigma"))
              .select("date", "symbol", "turnover", "sigma"))
        eq = res.equity.filter(pl.col("date").is_between(per.start, per.end)).select("date", "equity").sort("date")
        f = (res.fills.filter(pl.col("date").is_between(per.start, per.end) & (pl.col("symbol") != "GOLDBEES"))
             .join(eq, on="date", how="left").join(px, on=["date", "symbol"], how="left")
             .with_columns((pl.col("shares").abs() * pl.col("price") / pl.col("equity")).alias("frac"))
             .select("date", "symbol", "frac", "turnover", "sigma"))
        bad = f.filter(pl.col("turnover").is_null() | (pl.col("turnover") <= 0) | pl.col("sigma").is_null())
        assert bad.height <= f.height * 0.01, bad
        _cache[name] = (eq, f.filter(pl.col("turnover") > 0).with_columns(pl.col("sigma").fill_null(pl.col("sigma").median())))
    return _cache[name]


def adjusted(name: str, size: float) -> tuple[pl.DataFrame, float]:
    """The sleeve's equity curve after impact at book size `size`, and its average yearly impact drag in %."""
    eq, f = sleeve(name)
    drag = (f.with_columns((Y * pl.col("sigma") * (pl.col("frac") * size / pl.col("turnover")).sqrt() * pl.col("frac"))
                           .alias("d")).group_by("date").agg(pl.col("d").sum()))
    e = (eq.join(drag, on="date", how="left").with_columns(pl.col("d").fill_null(0.0))
         .with_columns((pl.col("equity") / pl.col("equity").shift(1)).fill_null(1.0).alias("g"))
         .with_columns(((pl.col("g") * (1 - pl.col("d"))).cum_prod() * eq["equity"][0]).alias("adj")))
    years = (e["date"][-1] - e["date"][0]).days / 365.25
    return e.select("date", "adj"), float(e["d"].sum()) / years * 100


def stats(e: pl.DataFrame) -> tuple[float, float, float]:
    v = e["adj"].to_numpy()
    years = (e["date"][-1] - e["date"][0]).days / 365.25
    cagr = ((v[-1] / v[0]) ** (1 / years) - 1) * 100
    peak, dd = -math.inf, 0.0
    for x in v:
        peak = max(peak, x)
        dd = max(dd, 1 - x / peak)
    return cagr, dd * 100, cagr / (dd * 100)


for book, parts in BOOKS.items():
    for size in (0.0, *SIZES):
        curves, drags = [], []
        for name, w in parts:
            e, d = adjusted(name, size * w)
            curves.append(e.with_columns((pl.col("adj") / e["adj"][0] * w).alias("adj")))
            drags.append(d * w)
        mix = curves[0]
        for c in curves[1:]:
            mix = mix.join(c, on="date", how="inner").with_columns((pl.col("adj") + pl.col("adj_right")).alias("adj")).drop("adj_right")
        cagr, dd, cal = stats(mix.sort("date"))
        print(f"{book} @ Rs {size / 1e5:,.0f} lakh: impact {sum(drags):.2f}%/yr; CAGR {cagr:.2f}% max DD {dd:.2f}% Calmar {cal:.3f}")
