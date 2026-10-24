"""M141: per-decision flags from NSE quarterly results (`mb.sources.nse_results.load`), point in time.

Each (symbol, quarter) uses its first filing: the figures known when the quarter was first reported. Later re-filings
(restatements, late XBRL copies) are ignored, so no later knowledge leaks in.
"""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl


def first_filings(filings: pl.DataFrame) -> pl.DataFrame:
    """One row per (symbol, period_end): the earliest-available filing with a net profit."""
    return (filings.filter(pl.col("net_profit").is_not_null())
            .sort("symbol", "period_end", "avail", "seq")
            .unique(["symbol", "period_end"], keep="first", maintain_order=True)
            .select("symbol", "period_end", "avail", "net_profit"))


def _quarter_back(d: date, k: int) -> tuple[int, int]:
    """(year, month) of the quarter end k quarters before the quarter ending in d's month."""
    m = d.year * 12 + (d.month - 1) - 3 * k
    return m // 12, m % 12 + 1


def flags(filings: pl.DataFrame, rule: str, decisions: list[date], max_age_days: int) -> dict[date, dict[str, float]]:
    """Decision -> symbol -> -1.0 for names the rule flags; names with too little data are not flagged.

    At decision d a symbol's latest quarter is its newest first filing with avail <= d, if that quarter ended at most
    `max_age_days` before d. Rules:
    - `loss`: the latest quarter and the three before it (all known at d) sum to a net loss or zero.
    - `yoy_decline`: the latest quarter's net profit is below the same quarter a year earlier (known at d).
    """
    if rule not in ("loss", "yoy_decline"):
        raise ValueError(f"unknown fundamentals rule {rule}")
    q = first_filings(filings)
    by_sym: dict[str, list[tuple[date, date, float]]] = {}
    for s, pe, av, npf in q.iter_rows():
        by_sym.setdefault(s, []).append((pe, av, npf))
    out: dict[date, dict[str, float]] = {}
    for d in decisions:
        flagged: dict[str, float] = {}
        for s, rows in by_sym.items():
            known = {(pe.year, pe.month): npf for pe, av, npf in rows if av <= d}
            if not known:
                continue
            last = max(pe for pe, av, _ in rows if av <= d)
            if (d - last).days > max_age_days:
                continue
            if rule == "loss":
                ks = [_quarter_back(last, k) for k in range(4)]
                if all(k in known for k in ks) and sum(known[k] for k in ks) <= 0.0:
                    flagged[s] = -1.0
            else:
                prev = _quarter_back(last, 4)
                if prev in known and known[(last.year, last.month)] < known[prev]:
                    flagged[s] = -1.0
        out[d] = flagged
    return out


def coverage(filings: pl.DataFrame, decisions: list[date], max_age_days: int) -> dict[date, set[str]]:
    """Decision -> symbols with a latest quarter no older than max_age_days (information only)."""
    q = first_filings(filings)
    out: dict[date, set[str]] = {}
    for d in decisions:
        w = q.filter(pl.col("avail") <= d).group_by("symbol").agg(pl.col("period_end").max())
        out[d] = set(w.filter(pl.col("period_end") >= d - timedelta(days=max_age_days))["symbol"].to_list())
    return out
