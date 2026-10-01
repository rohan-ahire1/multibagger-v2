"""M34 capacity check (docs/research/m34.md): the M13/M20 measure for the ₹2 crore floor on book invvol_b1.

Run: uv run python notebooks/m33_capacity.py. share = fill value / book equity that day × book size / turnover.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.strategy.momentum.run import simulate

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 0.05

for name in ("m33_adv2cr_gold20_b2", "m34_adv2cr_gold20_invvol_b1"):
    cfg = load_strategy_config(ROOT / f"strategies/momentum/configs/{name}.yaml", ROOT)
    res = simulate(cfg, ROOT)
    turnover = (pl.scan_parquet(datasets.dataset_path(ROOT, cfg.strategy.dataset) / datasets.PANEL_FILE)
                .select("date", "symbol", "turnover").collect())
    per = cfg.strategy.period
    cap = cfg.params.initial_capital
    f = (res.fills.filter(pl.col("date").is_between(per.start, per.end))
         .join(turnover, on=["date", "symbol"], how="left")
         .join(res.equity.select("date", "equity"), on="date", how="left")
         .with_columns((pl.col("shares").abs() * pl.col("price") / pl.col("equity") * cap / pl.col("turnover")).alias("share")))
    s = f.filter(pl.col("symbol") != "GOLDBEES")["share"].drop_nulls()
    p95 = s.quantile(0.95)
    print(f"{name}: stock fills {s.len()}; share of day's turnover, book ₹{cap / 1e5:.0f} lakh: median {s.median():.4%}, "
          f"p95 {p95:.4%}, max {s.max():.3%}; p95 reaches {LIMIT:.0%} at ₹{cap * LIMIT / p95 / 1e7:.1f} crore; "
          f"fills over 5% / 20% of the day at ₹10 lakh: {(s > 0.05).sum()} / {(s > 0.2).sum()}")
    big = f.filter(pl.col("share") > 0.2).select("date", "symbol", "shares", "price", "turnover", "share")
    print(big)
