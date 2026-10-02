"""Link a renamed stock's bars to its later symbol (M14, docs/research/m14.md).

Indicators are computed per symbol, so a rename (same ISIN, new symbol) would start the stock's history again.
"""
from __future__ import annotations

import polars as pl

LINK_SCHEMA = {"old": pl.Utf8, "new": pl.Utf8, "isin": pl.Utf8, "before": pl.Date, "final": pl.Utf8}
REFUSED_SCHEMA = {"old": pl.Utf8, "new": pl.Utf8, "isin": pl.Utf8, "before": pl.Date, "reason": pl.Utf8}


def _candidates(bars: pl.DataFrame, max_gap_days: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Consecutive symbols of one ISIN: links where the spans do not overlap and the gap between them is at most
    `max_gap_days` calendar days; refusals otherwise."""
    spans = (bars.filter(pl.col("security_id").str.starts_with("isin:"))
             .group_by("security_id", "symbol").agg(pl.col("date").min().alias("first"), pl.col("date").max().alias("last"))
             .sort("security_id", "first", "symbol")
             .with_columns(pl.col("symbol").shift(-1).over("security_id").alias("new"),
                           pl.col("first").shift(-1).over("security_id").alias("before"))
             .filter(pl.col("new").is_not_null())
             .select(pl.col("symbol").alias("old"), "new", pl.col("security_id").alias("isin"), "before", "last"))
    gap = (pl.col("before") - pl.col("last")).dt.total_days()
    ok = spans.filter((pl.col("last") < pl.col("before")) & (gap <= max_gap_days)).drop("last")
    overlap = spans.filter(pl.col("last") >= pl.col("before")).drop("last").with_columns(pl.lit("overlap").alias("reason"))
    stale = spans.filter(gap > max_gap_days).drop("last").with_columns(pl.lit("gap").alias("reason"))
    return ok, pl.concat([overlap, stale])


def _resolve(links: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Adds `final`: follow old -> new, then new's next rename dated on or after this one, until none is left."""
    rows = sorted(links.iter_rows(named=True), key=lambda r: (r["before"], r["old"]))
    by_old: dict[str, list[dict]] = {}
    for r in rows:
        by_old.setdefault(r["old"], []).append(r)
    done, cycles = [], []
    for r in rows:
        target, when, seen = r["new"], r["before"], {r["old"]}
        while True:
            nxt = [x for x in by_old.get(target, []) if x["before"] >= when]
            if not nxt:
                break
            if target in seen:
                target = None
                break
            seen.add(target)
            target, when = nxt[0]["new"], nxt[0]["before"]
        if target is None:
            cycles.append({**r, "reason": "cycle"})
        else:
            done.append({**r, "final": target})
    return (pl.DataFrame(done, schema=LINK_SCHEMA, orient="row") if done else pl.DataFrame(schema=LINK_SCHEMA),
            pl.DataFrame(cycles, schema=REFUSED_SCHEMA, orient="row") if cycles else pl.DataFrame(schema=REFUSED_SCHEMA))


def relabel(frame: pl.DataFrame, links: pl.DataFrame, date_col: str) -> pl.DataFrame:
    """Rows of a linked `old` symbol dated on or before its link's `before` take the link's `final` symbol."""
    if links.is_empty() or frame.is_empty():
        return frame
    m = links.select(pl.col("old").alias("symbol"), pl.col("before").alias("_before"), pl.col("final").alias("_to")).sort("_before")
    out = (frame.with_row_index("_i").sort(date_col)
           .join_asof(m, left_on=date_col, right_on="_before", by="symbol", strategy="forward", check_sortedness=False)
           .sort("_i"))
    return out.with_columns(pl.coalesce("_to", "symbol").alias("symbol")).drop("_i", "_before", "_to")


def rename_links(bars: pl.DataFrame, max_gap_days: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(links, refused). A link is refused if its spans overlap or are too far apart, it is part of a cycle, or relabelling would give one
    symbol two bars on one session; dropping one link can change another's `final`, so this repeats until clean."""
    links, refused = _candidates(bars, max_gap_days)
    refused = [refused]
    while True:
        resolved, cycles = _resolve(links)
        refused.append(cycles)
        moved = relabel(bars.select("date", "symbol").with_columns(pl.col("symbol").alias("_orig")), resolved, "date")
        clash = moved.filter(pl.len().over("date", "symbol") > 1).filter(pl.col("symbol") != pl.col("_orig"))
        bad = resolved.join(clash.select(pl.col("_orig").alias("old"), pl.col("symbol").alias("final")).unique(),
                            on=["old", "final"], how="semi")
        if bad.is_empty():
            return resolved, pl.concat(refused).sort("before", "old")
        refused.append(bad.drop("final").with_columns(pl.lit("two bars on one session").alias("reason")))
        links = links.join(bad.select("old", "new", "before"), on=["old", "new", "before"], how="anti")
