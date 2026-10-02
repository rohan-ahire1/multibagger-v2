"""M70 (docs/research/m70.md): the M52 stitched walk-forward with the half-rotation rule, 2014-2023 (information).

Piece k uses only the setting M42 chose from earlier data (A for 2014-17, B for 2018-20, C for 2021-23). Within a
piece the money starts split equally over the given sleeves and is never rebalanced; pieces are chained.
Run: uv run python notebooks/m70_stitched_half.py.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OFFSETS = ("", "_off5", "_off10", "_off15")
PIECES = [("a", date(2014, 1, 1), date(2017, 12, 31)), ("b", date(2018, 1, 1), date(2020, 12, 31)),
          ("c", date(2021, 1, 1), date(2023, 12, 31))]


def run_ids() -> dict[str, str]:
    ids: dict[str, str] = {}
    for f in ("m49_runs.txt", "m59_runs.txt", "m70_runs.txt"):
        for line in (ROOT / "reports" / f).read_text().splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1] == "run":
                ids.setdefault(parts[0], parts[2])
    return ids


IDS = run_ids()


def book(x: str, off: str) -> str:
    return f"m49_{x}{off}_b2"


def rot(x: str, off: str) -> str:
    return f"m59_rot{off}_b2" if x == "b" else f"m70_rot_{x}{off}_b2"


def equity(cfg: str) -> pl.DataFrame:
    return pl.read_parquet(ROOT / f"runs/{IDS[cfg]}/equity.parquet").select("date", "equity").sort("date")


def piece(cfgs: list[str], a: date, b: date) -> pl.DataFrame:
    """Daily returns over [a, b] of equal starting money in each config, from the last close before a."""
    curves = []
    for c in cfgs:
        e = equity(c)
        start = e.filter(pl.col("date") < a)["equity"][-1]
        curves.append(e.filter(pl.col("date").is_between(a, b)).select("date", (pl.col("equity") / start).alias(c)))
    m = curves[0]
    for c in curves[1:]:
        m = m.join(c, on="date", how="inner")
    assert m.height == curves[0].height
    v = m.select("date", pl.mean_horizontal(cfgs).alias("v"))
    return v.with_columns((pl.col("v") / pl.col("v").shift(1).fill_null(1.0) - 1).alias("r")).select("date", "r")


def stats(r: pl.DataFrame) -> str:
    eq = (1 + r["r"]).cum_prod()
    years = (r["date"][-1] - r["date"][0]).days / 365.25
    cagr = eq[-1] ** (1 / years) - 1
    dd = (1 - eq / eq.cum_max().clip(lower_bound=1.0)).max()
    return f"CAGR {cagr:.2%} max DD {dd:.2%} Calmar {cagr / dd:.3f}"


BOOKS = {
    "book, offset 0 (M52)": lambda x: [book(x, "")],
    "half, offset 0": lambda x: [book(x, ""), rot(x, "")],
    "book, 4 tranches": lambda x: [book(x, o) for o in OFFSETS],
    "half, 4 tranches": lambda x: [c for o in OFFSETS for c in (book(x, o), rot(x, o))],
}
for name, cfgs in BOOKS.items():
    parts = [piece(cfgs(x), a, b) for x, a, b in PIECES]
    print(f"{name} 2014-2023: {stats(pl.concat(parts))}")
    for (x, a, b), p in zip(PIECES, parts):
        print(f"    {a.year}-{b.year} ({x}): {stats(p)}")
