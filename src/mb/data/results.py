"""M114: the market's reaction to each quarterly results meeting (NSE board-meeting announcements)."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

STALE_DAYS = 14  # a decision this many days after the last announced meeting has no data behind it


def load(raw_dir: Path) -> pl.DataFrame:
    """One row per results meeting: symbol, meeting (date)."""
    files = sorted(raw_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no board-meeting files in {raw_dir}")
    x = pl.concat([pl.read_parquet(f, columns=["bm_symbol", "bm_date", "bm_purpose", "bm_desc"]) for f in files])
    hit = (pl.col("bm_purpose").str.to_lowercase().str.contains("result")
           | pl.col("bm_desc").str.to_lowercase().str.contains("financial result"))
    return (x.filter(hit.fill_null(False))
            .select(pl.col("bm_symbol").alias("symbol"), pl.col("bm_date").str.strptime(pl.Date, "%d-%b-%Y").alias("meeting"))
            .drop_nulls().unique().sort("symbol", "meeting"))


def reactions(meetings: pl.DataFrame, panel: pl.DataFrame, benchmark: str) -> pl.DataFrame:
    """symbol, meeting, post (first session after the meeting), reaction: adjusted close return from the last session
    before the meeting to `post`, minus the benchmark's (null if a close is missing). Meetings without a session on
    both sides in the panel are dropped."""
    days = pl.DataFrame({"d": sorted(panel["date"].unique().to_list())}).with_row_index("i")
    m = (meetings.sort("meeting")
         .join_asof(days.rename({"d": "pre"}), left_on="meeting", right_on="pre", strategy="backward",
                    allow_exact_matches=False)
         .join_asof(days.rename({"d": "post", "i": "j"}), left_on="meeting", right_on="post", strategy="forward",
                    allow_exact_matches=False)
         .drop_nulls(["pre", "post"]))
    px = panel.select("date", "symbol", "adj_close")
    bench = px.filter(pl.col("symbol") == benchmark).select("date", pl.col("adj_close").alias("b"))
    for side in ("pre", "post"):
        m = (m.join(px.rename({"date": side, "adj_close": f"c_{side}"}), on=[side, "symbol"], how="left")
             .join(bench.rename({"date": side, "b": f"b_{side}"}), on=side, how="left"))
    return m.select("symbol", "meeting", "post",
                    (pl.col("c_post") / pl.col("c_pre") - pl.col("b_post") / pl.col("b_pre")).alias("reaction"))


def signal_by_decision(r: pl.DataFrame, meetings: pl.DataFrame, decisions: list[date],
                       lookback_days: int) -> dict[date, dict[str, float]]:
    """Decision -> symbol -> reaction to its latest results meeting usable at d (post <= d) held within
    `lookback_days` before d. A symbol whose latest such meeting has no reaction gets no entry."""
    last = meetings["meeting"].max()
    assert isinstance(last, date)
    out: dict[date, dict[str, float]] = {}
    for d in decisions:
        if d > last + timedelta(days=STALE_DAYS):
            raise ValueError(f"board-meeting data ends {last}; decision {d} has no data behind it")
        w = (r.filter((pl.col("post") <= d) & (pl.col("meeting") >= d - timedelta(days=lookback_days)))
             .sort("meeting").group_by("symbol").last().drop_nulls("reaction"))
        out[d] = dict(w.select("symbol", "reaction").iter_rows())
    return out
