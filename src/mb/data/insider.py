"""M111: insider open-market trades (SEBI PIT disclosures from NSE) as a per-decision signal."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

BUY_MODE, SELL_MODE = "Market Purchase", "Market Sale"
DEDUP_KEY = ["symbol", "acqName", "acqfromDt", "acqtoDt", "secAcq", "acqMode"]
COLUMNS = [*DEDUP_KEY, "personCategory", "date", "secVal"]
FILING_COLUMNS = ["appId", "prevAppId"]  # XBRL feed only (M112): a revision names the filing it replaces
STALE_DAYS = 7  # a decision this many days after the last broadcast has no data behind it


def load(raw_dir: Path, categories: list[str]) -> pl.DataFrame:
    """One row per kept trade: symbol, avail (first date it may be used: the day after the NSE broadcast), value
    (Rs, + buy / - sell)."""
    files = sorted(raw_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no insider files in {raw_dir}")
    parts = []
    for f in files:
        have = pl.read_parquet_schema(f)
        parts.append(pl.read_parquet(f, columns=COLUMNS + [c for c in FILING_COLUMNS if c in have]).with_columns(
            [pl.col(c).cast(pl.String) for c in COLUMNS + [c for c in FILING_COLUMNS if c in have]]
            + [pl.lit(None, pl.String).alias(c) for c in FILING_COLUMNS if c not in have]))
    x = pl.concat(parts, how="vertical")
    replaced = x["prevAppId"].drop_nulls().unique().implode()
    x = x.filter(pl.col("appId").is_null() | ~pl.col("appId").is_in(replaced))
    x = (x.filter(pl.col("acqMode").is_in([BUY_MODE, SELL_MODE]) & pl.col("personCategory").is_in(categories))
         .unique(subset=DEDUP_KEY, keep="first", maintain_order=True)
         .with_columns(pl.col("date").str.strptime(pl.Datetime, "%d-%b-%Y %H:%M").dt.date().alias("broadcast"),
                       pl.col("secVal").cast(pl.Float64, strict=False).alias("v"))
         .filter(pl.col("v").is_not_null()))
    return x.select("symbol", (pl.col("broadcast") + timedelta(days=1)).alias("avail"),
                    pl.when(pl.col("acqMode") == BUY_MODE).then(pl.col("v")).otherwise(-pl.col("v")).alias("value"))


def net_by_decision(trades: pl.DataFrame, decisions: list[date], lookback_days: int) -> dict[date, dict[str, float]]:
    """Decision date -> symbol -> net value of trades usable at the decision (avail <= d) and broadcast in the
    lookback window (avail > d - lookback_days). Decisions before the data covers a full window get no entry (the rule
    is off); a decision past the data's end is an error."""
    first, last = trades["avail"].min(), trades["avail"].max()
    assert isinstance(first, date) and isinstance(last, date)
    out: dict[date, dict[str, float]] = {}
    for d in decisions:
        if d > last + timedelta(days=STALE_DAYS):
            raise ValueError(f"insider data ends {last}; decision {d} has no data behind it")
        if d - timedelta(days=lookback_days - 1) < first:  # the window (d - lookback, d] starts before the data
            continue
        w = trades.filter((pl.col("avail") <= d) & (pl.col("avail") > d - timedelta(days=lookback_days)))
        out[d] = dict(w.group_by("symbol").agg(pl.col("value").sum()).iter_rows())
    return out
