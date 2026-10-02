"""M87 (docs/research/m87.md): M39's circuit check on the 10%-stop books, with a cost estimate (information).

A sell on a locked-down day (high == low, close below the previous close) could not fill. Here it is assumed to fill at
the open of the next session that is not locked down. The extra loss of each such sell, (1 - that open / the day's
open) x the sold value, is charged as a fraction of the run's equity on the sell day; the drag is the sum per year.
The pin (no stop) is the comparison.
Run: uv run python notebooks/m87_stop_circuits.py
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
RUNS = {"pin m49_b_b2": "20261002-000607-0103cc7f", "stop10 m72_stop10_b2": "20261002-012910-34c96cab",
        "stop10 off5": "20261002-013029-6d78c1e2", "stop10 off10": "20261002-013011-60735e0e",
        "stop10 off15": "20261002-013020-3949945f", "rot_s10 m78_rot_s10_b2": "20261002-021129-8a695cf6",
        "g0s10 m86_g0s10_b2": "20261002-030829-77e725bf"}
panel = (pl.scan_parquet(ROOT / "data/datasets/nse_research/2026-10-02b/panel.parquet").filter(pl.col("series") == "EQ")
         .select("date", "symbol", "open", "high", "low", "close").sort("symbol", "date")
         .with_columns(pl.col("close").shift(1).over("symbol").alias("prev")).collect())
down = (pl.col("high") == pl.col("low")) & (pl.col("close") < pl.col("prev"))
# For each locked-down day, the open of the next session of that symbol that is not locked down.
p = panel.with_columns(down.alias("ld")).with_columns(
    pl.when(~pl.col("ld")).then(pl.col("open")).shift(-1).backward_fill().over("symbol").alias("next_open"))
for name, run in RUNS.items():
    t = pl.read_parquet(ROOT / f"runs/{run}/trades.parquet").filter((pl.col("symbol") != "GOLDBEES") & (pl.col("status") != "open"))
    eq = pl.read_parquet(ROOT / f"runs/{run}/equity.parquet").select("date", "equity")
    sells = (t.select("symbol", pl.col("exit_date").alias("date"), pl.col("sold").alias("value"))
             .join(p, on=["symbol", "date"], how="left").join(eq, on="date", how="left"))
    sl = sells.filter(pl.col("ld"))
    cost = sl.select(((1 - pl.col("next_open") / pl.col("open")) * pl.col("value") / pl.col("equity")).alias("c"))
    years = (eq["date"][-1] - eq["date"][0]).days / 365.25
    print(f"{name}: {sells.height} exits, locked down {sl.height}; extra loss {cost['c'].sum():.2%} of equity in total, "
          f"{cost['c'].sum() / years:.3%} a year; worst {cost['c'].max() if sl.height else 0:.2%}")
    if sl.height:
        print("   ", sl.select("symbol", "date", (1 - pl.col("next_open") / pl.col("open")).round(3).alias("extra"))
              .sort("date").rows()[:12])
