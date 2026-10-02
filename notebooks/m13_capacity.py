"""M13 capacity check (docs/research/m13.md): each fill's value as a share of that symbol's raw turnover that session.

Run: uv run python notebooks/m13_capacity.py. The backtest book compounds (₹10 lakh grows ~20×), so each fill is first
scaled to a book of fixed size: share = fill value / book equity that day × book size / turnover. Shares are linear in
book size. The M14 configs (rename-linked dataset) are added after the pre-registered M13 ones.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.strategy.momentum.run import simulate

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 0.05  # p95 fill share of a day's turnover the pre-registration asks about

for name in ("m13_clean_b2", "m13_clean_invvol_b2", "m13_clean_b1", "m13_clean_invvol_b1",
             "m14_linked_b2", "m14_linked_invvol_b2", "m14_linked_b1", "m14_linked_invvol_b1"):
    cfg = load_strategy_config(ROOT / f"strategies/momentum/configs/{name}.yaml", ROOT)
    res = simulate(cfg, ROOT)
    turnover = (pl.scan_parquet(datasets.dataset_path(ROOT, cfg.strategy.dataset) / datasets.PANEL_FILE)
                .select("date", "symbol", "turnover").collect())
    per = cfg.strategy.period
    f = (res.fills.filter(pl.col("date").is_between(per.start, per.end))
         .join(turnover, on=["date", "symbol"], how="left")
         .join(res.equity.select("date", "equity"), on="date", how="left")
         .with_columns((pl.col("shares").abs() * pl.col("price") / pl.col("equity") * cfg.params.initial_capital
                        / pl.col("turnover")).alias("share")))
    s = f["share"].drop_nulls()
    p95 = s.quantile(0.95)
    cap = cfg.params.initial_capital
    print(f"{name}: fills {f.height}, no bar or equity {f['share'].null_count()}; share of day's turnover, book ₹{cap / 1e5:.0f} lakh: "
          f"median {s.median():.5%}, p95 {p95:.4%}, max {s.max():.3%}; p95 reaches {LIMIT:.0%} at ₹{cap * LIMIT / p95 / 1e7:.1f} crore")
