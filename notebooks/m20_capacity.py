"""M20 capacity check (docs/research/m20.md): the M13 measure for the M19 gold sleeve, GOLDBEES fills and all fills.

Run: uv run python notebooks/m20_capacity.py. share = fill value / book equity that day × book size / turnover.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.strategy.momentum.run import simulate

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 0.05

cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m19_gold20_invvol_b2.yaml", ROOT)
res = simulate(cfg, ROOT)
turnover = (pl.scan_parquet(datasets.dataset_path(ROOT, cfg.strategy.dataset) / datasets.PANEL_FILE)
            .select("date", "symbol", "turnover").collect())
per = cfg.strategy.period
cap = cfg.params.initial_capital
f = (res.fills.filter(pl.col("date").is_between(per.start, per.end))
     .join(turnover, on=["date", "symbol"], how="left")
     .join(res.equity.select("date", "equity"), on="date", how="left")
     .with_columns((pl.col("shares").abs() * pl.col("price") / pl.col("equity") * cap / pl.col("turnover")).alias("share")))
for label, g in (("GOLDBEES", f.filter(pl.col("symbol") == "GOLDBEES")), ("all", f)):
    s = g["share"].drop_nulls()
    p95 = s.quantile(0.95)
    print(f"{label}: fills {g.height}, no bar or equity {g['share'].null_count()}; share of day's turnover, book ₹{cap / 1e5:.0f} lakh: "
          f"median {s.median():.5%}, p95 {p95:.4%}, max {s.max():.3%}; p95 reaches {LIMIT:.0%} at ₹{cap * LIMIT / p95 / 1e7:.1f} crore")
