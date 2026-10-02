"""M52 (docs/research/m52.md): the M42 walk-forward process as one out-of-sample curve, 2014-2023.

Each month's return comes from the setting M42 selected using only earlier data: step A (trained 2010-13) for
2014-17, step B (2010-17) for 2018-20, step C (2010-20) for 2021-23. Daily returns are taken from the offset-0 M49
runs (each starts 2010-01-04, so every book is warm), and chained. Run: uv run python notebooks/m52_stitched.py.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
RUNS = {"a": "20261002-000447-e95b8299", "b": "20261002-000352-0103cc7f", "c": "20261002-000306-0ff2d949",
        "old_pin": "20261001-223048-0545e2d7"}
PIECES = [("a", date(2014, 1, 1), date(2017, 12, 31)), ("b", date(2018, 1, 1), date(2020, 12, 31)),
          ("c", date(2021, 1, 1), date(2023, 12, 31))]


def rets(run: str) -> pl.DataFrame:
    e = pl.read_parquet(ROOT / f"runs/{run}/equity.parquet").select("date", "equity").sort("date")
    return e.with_columns((pl.col("equity") / pl.col("equity").shift(1) - 1).alias("r")).drop_nulls("r")


def stats(r: pl.DataFrame) -> str:
    eq = (1 + r["r"]).cum_prod()
    years = (r["date"][-1] - r["date"][0]).days / 365.25
    cagr = eq[-1] ** (1 / years) - 1
    dd = (1 - eq / eq.cum_max()).max()
    return f"CAGR {cagr:.2%} max DD {dd:.2%} Calmar {cagr / dd:.3f}"


stitched = pl.concat([rets(RUNS[k]).filter(pl.col("date").is_between(a, b)) for k, a, b in PIECES])
print("stitched walk-forward 2014-2023:", stats(stitched))
for k in ("old_pin", "b", "c", "a"):
    print(f"{k} 2014-2023:", stats(rets(RUNS[k]).filter(pl.col("date").is_between(date(2014, 1, 1), date(2023, 12, 31)))))
for k, a, b in PIECES:
    print(f"  {a.year}-{b.year} selected {k}:", stats(rets(RUNS[k]).filter(pl.col("date").is_between(a, b))),
          "| old pin:", stats(rets(RUNS["old_pin"]).filter(pl.col("date").is_between(a, b))))
