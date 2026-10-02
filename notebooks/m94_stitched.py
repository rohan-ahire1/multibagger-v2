"""M94 (docs/research/m94.md): the M52 stitched walk-forward for M93's g25gt rule (gold 0.25 held while it trends up, 10% stop, 200-day filter
with the risk-off share in gold), 2014-2023 (information).

Piece k uses only the setting M42 chose from earlier data (A for 2014-17, B for 2018-20, C for 2021-23). Within a
piece the money starts split equally over the given sleeves and is never rebalanced; pieces are chained.
Run: uv run python notebooks/m94_stitched.py.
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
    for f in ("m49_runs.txt", "m59_runs.txt", "m70_runs.txt", "m72_runs.txt", "m73_runs.txt", "m78_runs.txt",
              "m85_runs.txt", "m89_runs.txt", "m90_runs.txt", "m93_runs.txt", "m94_runs.txt"):
        for line in (ROOT / "reports" / f).read_text().splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1] == "run":
                ids.setdefault(parts[0], parts[2])
    return ids


IDS = run_ids()


def book(x: str, off: str, rule: str) -> str:
    if rule == "plain":
        return f"m49_{x}{off}_b2"
    if rule == "stop":
        if x == "b":
            return "m72_stop10_b2" if off == "" else f"m73_stop10{off}_b2"
        return f"m85_{x}_s10{off}_b2"
    if rule == "g25gt":
        return f"m93_g25s10_r50g_gt{off}_b2" if x == "b" else f"m94_{x}_g25gt{off}_b2"
    return f"m89_g0s10_{rule}{off}_b2" if x == "b" else f"m90_{x}_{rule}{off}_b2"


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


for rule in ("plain", "r50g", "g25gt"):
    books = {
        f"{rule}, offset 0": lambda x: [book(x, "", rule)],
        f"{rule}, 4 tranches": lambda x: [book(x, o, rule) for o in OFFSETS],
    }
    for name, cfgs in books.items():
        parts = [piece(cfgs(x), a, b) for x, a, b in PIECES]
        print(f"{name} 2014-2023: {stats(pl.concat(parts))}")
        for (x, a, b), p in zip(PIECES, parts):
            print(f"    {a.year}-{b.year} ({x}): {stats(p)}")
