"""M39 (docs/research/m39.md): how many entry/exit fills fall on days the stock was locked at a price band.

Locked day: high == low (no range all day). Locked up: locked and close above the previous close (no sellers, a buy
could not fill); locked down: below (no buyers, a sell could not fill). Also "open at the band": the open equals the
day's high (buy) or low (sell) and the open is at least 4.9% from the previous close.
Run: uv run python notebooks/m39_circuits.py
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
RUNS = {"pin ₹2 cr": "20261001-135135-a38245bf", "₹5 cr (m33_gold20_invvol_b2)": "20261001-135126-7b9bc445"}
panel = (pl.scan_parquet(ROOT / "data/datasets/nse_research/2026-10-01b/panel.parquet").filter(pl.col("series") == "EQ")
         .select("date", "symbol", "open", "high", "low", "close").sort("symbol", "date")
         .with_columns(pl.col("close").shift(1).over("symbol").alias("prev")).collect())
for name, run in RUNS.items():
    t = pl.read_parquet(ROOT / f"runs/{run}/trades.parquet").filter(pl.col("symbol") != "GOLDBEES")
    buys = t.select("symbol", pl.col("entry_date").alias("date"), (pl.col("bought")).alias("value")).join(panel, on=["symbol", "date"], how="left")
    sells = t.filter(pl.col("status") != "open").select("symbol", pl.col("exit_date").alias("date"), pl.col("sold").alias("value")).join(panel, on=["symbol", "date"], how="left")
    locked = (pl.col("high") == pl.col("low"))
    bl = buys.filter(locked & (pl.col("close") > pl.col("prev")))
    bo = buys.filter((pl.col("open") == pl.col("high")) & (pl.col("open") / pl.col("prev") - 1 >= 0.049))
    sl = sells.filter(locked & (pl.col("close") < pl.col("prev")))
    so = sells.filter((pl.col("open") == pl.col("low")) & (1 - pl.col("open") / pl.col("prev") >= 0.049))
    print(f"{name}: {buys.height} entries, locked up {bl.height}, open at upper band {bo.height}; "
          f"{sells.height} exits, locked down {sl.height}, open at lower band {so.height}; missing bars "
          f"{buys['open'].null_count() + sells['open'].null_count()}")
    for lab, df in (("locked up buys", bl), ("locked down sells", sl), ("upper-band-open buys", bo), ("lower-band-open sells", so)):
        if df.height:
            print(" ", lab, df.select("symbol", "date", (pl.col("open") / pl.col("prev") - 1).round(3).alias("gap")).sort("date").rows()[:15])
