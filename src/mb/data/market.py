"""M118: market-level F&O signals (India VIX, NIFTY option put-call ratio, FII index futures positioning) as a
per-decision risk-on flag."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

STALE_DAYS = 7  # a decision this many days after the latest usable value has no data behind it


def _files(raw_dir: Path) -> list[Path]:
    files = sorted(raw_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no files in {raw_dir}")
    return files


def load_vix(raw_dir: Path) -> pl.DataFrame:
    """avail, value: India VIX close, usable on its own date (an index close)."""
    x = pl.concat([pl.read_parquet(f, columns=["EOD_TIMESTAMP", "EOD_CLOSE_INDEX_VAL"]) for f in _files(raw_dir)])
    return (x.select(pl.col("EOD_TIMESTAMP").str.to_titlecase().str.strptime(pl.Date, "%d-%b-%Y").alias("avail"),
                     pl.col("EOD_CLOSE_INDEX_VAL").cast(pl.Float64).alias("value"))
            .unique("avail", keep="first", maintain_order=True).sort("avail"))


def load_pcr(raw_dir: Path, symbol: str) -> pl.DataFrame:
    """avail, value: total put / total call open interest over all of `symbol`'s index option expiries, usable the day
    after (NSE publishes the bhavcopy in the evening)."""
    x = pl.concat([pl.scan_parquet(f).filter((pl.col("instrument") == "OPTIDX") & (pl.col("sym") == symbol))
                   .select("d", "opt", "oi").collect() for f in _files(raw_dir)])
    g = x.group_by("d").agg(pl.col("oi").filter(pl.col("opt") == "PE").sum().alias("put"),
                            pl.col("oi").filter(pl.col("opt") == "CE").sum().alias("call"))
    if g.is_empty() or (g["call"] <= 0).any():
        raise ValueError(f"no {symbol} index options, or a day with no call open interest, in {raw_dir}")
    return g.select((pl.col("d") + timedelta(days=1)).alias("avail"), (pl.col("put") / pl.col("call")).alias("value")).sort("avail")


def load_fii_long_share(raw_dir: Path) -> pl.DataFrame:
    """avail, value: FII index futures long / (long + short) contracts, usable the day after (published in the evening)."""
    x = pl.concat([pl.read_parquet(f, columns=["d", "client_type", "fut_idx_long", "fut_idx_short"])
                   for f in _files(raw_dir)]).filter(pl.col("client_type") == "FII")
    tot = pl.col("fut_idx_long") + pl.col("fut_idx_short")
    if x.is_empty() or (x["fut_idx_long"] + x["fut_idx_short"] <= 0).any():
        raise ValueError(f"no FII rows, or a day with no FII index futures, in {raw_dir}")
    return (x.select((pl.col("d") + timedelta(days=1)).alias("avail"), (pl.col("fut_idx_long") / tot).alias("value"))
            .unique("avail", keep="first", maintain_order=True).sort("avail"))


def _latest(s: pl.DataFrame, decisions: list[date]) -> dict[date, int | None]:
    """Decision -> row index of the latest value usable at it (avail <= d), None before the data starts. A decision more
    than STALE_DAYS after that value is an error."""
    avail = s["avail"].to_list()
    out: dict[date, int | None] = {}
    i = -1
    for d in sorted(decisions):
        while i + 1 < len(avail) and avail[i + 1] <= d:
            i += 1
        if i >= 0 and d > avail[i] + timedelta(days=STALE_DAYS):
            raise ValueError(f"market signal: latest value before {d} is from {avail[i]}")
        out[d] = i if i >= 0 else None
    return out


def ranked_on(s: pl.DataFrame, decisions: list[date], window: int, min_pct: float) -> dict[date, bool]:
    """False where the latest value ranks low against its last `window` values (itself included): the fraction of them
    strictly below it is under `min_pct`. True before a full window (the rule is off)."""
    v = s["value"].to_list()
    out: dict[date, bool] = {}
    for d, i in _latest(s, decisions).items():
        if i is None or i + 1 < window:
            out[d] = True
            continue
        w = v[i + 1 - window: i + 1]
        out[d] = sum(x < v[i] for x in w) / window >= min_pct
    return out


def vrp_on(vix: pl.DataFrame, panel: pl.DataFrame, symbol: str, rv_sessions: int, decisions: list[date]) -> dict[date, bool]:
    """False where the variance risk premium is negative: (VIX / 100)^2 / 12 below the sum of `symbol`'s squared daily
    log returns (adj_close) over the `rv_sessions` sessions to the decision. True before the VIX data starts."""
    b = (panel.filter(pl.col("symbol") == symbol).sort("date")
         .with_columns((pl.col("adj_close").log().diff() ** 2).rolling_sum(rv_sessions, min_samples=rv_sessions).alias("rv")))
    rv = {d: r for d, r in b.select("date", "rv").iter_rows() if r is not None}
    missing = [d for d in decisions if d not in rv]
    if missing:
        raise ValueError(f"vrp: {symbol} has no {rv_sessions}-session realised variance on {missing[:3]}")
    v = vix["value"].to_list()
    out: dict[date, bool] = {}
    for d, i in _latest(vix, decisions).items():
        out[d] = True if i is None else (v[i] / 100.0) ** 2 / 12.0 >= rv[d]
    return out
