"""M116: NSE bulk and block deals (from the uncapped CSV export) as a per-decision net-buying signal."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import polars as pl

COLUMNS = ["BD_DT_DATE", "BD_SYMBOL", "BD_CLIENT_NAME", "BD_BUY_SELL", "BD_QTY_TRD", "BD_TP_WATP"]


def load(raw_dirs: list[Path]) -> pl.DataFrame:
    """One row per deal: symbol, avail (the day after the deal: NSE publishes them that evening), value (Rs, + buy /
    - sell). The same deal listed twice in one folder (identical row) counts once."""
    parts = []
    for d in raw_dirs:
        files = sorted(d.glob("*.parquet"))
        if not files:
            raise FileNotFoundError(f"no deal files in {d}")
        parts.append(pl.concat([pl.read_parquet(f, columns=COLUMNS) for f in files]).unique(maintain_order=True))
    x = (pl.concat(parts)
         .with_columns(pl.col("BD_DT_DATE").str.to_titlecase().str.strptime(pl.Date, "%d-%b-%Y").alias("day"),
                       (pl.col("BD_QTY_TRD").cast(pl.Float64) * pl.col("BD_TP_WATP").cast(pl.Float64)).alias("v"),
                       pl.col("BD_BUY_SELL").str.strip_chars().str.to_uppercase().alias("side"))
         .filter(pl.col("side").is_in(["BUY", "SELL"]) & pl.col("v").is_not_null() & pl.col("day").is_not_null()))
    return x.select(pl.col("BD_SYMBOL").str.strip_chars().alias("symbol"), (pl.col("day") + timedelta(days=1)).alias("avail"),
                    pl.when(pl.col("side") == "BUY").then(pl.col("v")).otherwise(-pl.col("v")).alias("value"))
