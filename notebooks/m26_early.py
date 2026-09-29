"""M26: NIFTYBEES buy-and-hold over the early window, and each run's worst drawdown dates. One-off; never imported."""
from datetime import date
from pathlib import Path

import polars as pl

from mb.evaluation.metrics import equity_metrics

ROOT = Path(__file__).resolve().parents[1]
START, END = date(2007, 4, 2), date(2009, 12, 31)
RUNS = {"b1": "20260929-205843-79266764", "b2": "20260929-205844-eb3a7fba",
        "invvol_b1": "20260929-205845-92cf3409", "invvol_b2": "20260929-205846-2eb586d3",
        "gold20_b1": "20260929-205847-626bda6d", "gold20_b2": "20260929-205848-03992b6a",
        "gold20_invvol_b1": "20260929-205849-31afc53d", "gold20_invvol_b2": "20260929-205850-88ebd661",
        "gold30_invvol_b2": "20260929-205851-ae35cb4b"}


def worst(eq: pl.DataFrame) -> tuple[date, date, float]:
    eq = eq.filter(pl.col("date").is_between(START, END)).with_columns(pl.col("equity").cum_max().alias("peak"))
    eq = eq.with_columns((pl.col("equity") / pl.col("peak") - 1).alias("dd"))
    t = eq.sort("dd").row(0, named=True)
    p = eq.filter((pl.col("date") <= t["date"]) & (pl.col("equity") == t["peak"])).row(0, named=True)
    return p["date"], t["date"], t["dd"] * 100


panel = pl.scan_parquet(ROOT / "data/datasets/nse_research/2026-09-30d/panel.parquet")
for sym in ("NIFTYBEES", "GOLDBEES"):
    s = (panel.filter((pl.col("symbol") == sym) & pl.col("date").is_between(START, END))
         .select("date", pl.col("adj_close").alias("equity")).collect().sort("date"))
    m = equity_metrics(s, START, END)
    print(f"{sym:10s} {m['cagr_pct']:6.2f}% {m['max_dd_pct']:6.2f}% {m['calmar']:.3f}", *worst(s))
for name, run in RUNS.items():
    eq = pl.read_parquet(ROOT / "runs" / run / "equity.parquet")
    print(f"{name:18s}", *worst(eq))
