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


def first_share_filings(filings: pl.DataFrame) -> pl.DataFrame:
    """One row per (symbol, period_end) with shares = paid-up capital / face value, from the earliest filing that has
    both (M143)."""
    return (filings.filter(pl.col("paid_up").is_not_null() & (pl.col("face_value").fill_null(0.0) > 0.0)
                           & (pl.col("paid_up") > 0.0))
            .sort("symbol", "period_end", "avail", "seq")
            .unique(["symbol", "period_end"], keep="first", maintain_order=True)
            .select("symbol", "period_end", "avail", (pl.col("paid_up") / pl.col("face_value")).alias("shares")))


def turnover_ratio(filings: pl.DataFrame, panel: pl.DataFrame, decisions: list[date], sessions: int,
                   max_age_days: int) -> dict[date, dict[str, float]]:
    """M143: decision -> symbol -> mean daily traded value (raw `turnover`, last `sessions` sessions to d) / market cap
    at d. Market cap = shares from the latest share filing usable at d (quarter ended within max_age_days) x raw close
    at d x adj_factor(d) / adj_factor(last session on or before the quarter end), so splits and bonuses after the
    quarter carry the share count with them. Symbols without a usable filing or full turnover window are left out."""
    sh = first_share_filings(filings)
    px = (panel.select("date", "symbol", "close", "adj_factor", "turnover").sort("symbol", "date")
          .with_columns(pl.col("turnover").rolling_mean(sessions, min_samples=sessions).over("symbol").alias("adv")))
    at_d = px.filter(pl.col("date").is_in(decisions)).select("date", "symbol", "close", "adj_factor", "adv")
    # adj_factor at each filing's quarter end (as-of join on the symbol's sessions)
    qf = (sh.sort("period_end").join_asof(px.select("symbol", "date", pl.col("adj_factor").alias("af_q")).sort("date"),
                                          left_on="period_end", right_on="date", by="symbol", strategy="backward")
          .drop("date").filter(pl.col("af_q").is_not_null()))
    out: dict[date, dict[str, float]] = {}
    for d in decisions:
        usable = (qf.filter((pl.col("avail") <= d) & (pl.col("period_end") >= d - timedelta(days=max_age_days)))
                  .sort("period_end").group_by("symbol").agg(pl.all().last()))
        x = (at_d.filter(pl.col("date") == d).join(usable, on="symbol", how="inner")
             .filter(pl.col("adv").is_not_null())
             .with_columns((pl.col("shares") * pl.col("close") * pl.col("adj_factor") / pl.col("af_q")).alias("mcap"))
             .filter(pl.col("mcap") > 0.0))
        out[d] = dict(x.select("symbol", pl.col("adv") / pl.col("mcap")).iter_rows())
    return out


def ttm_profit(filings: pl.DataFrame, decisions: list[date], max_age_days: int) -> dict[date, dict[str, float]]:
    """M144: decision -> symbol -> net profit of the latest quarter and the three before it (first filings, all known
    at d, latest quarter ended within max_age_days). Symbols missing any of the four quarters are left out."""
    q = first_filings(filings)
    by_sym: dict[str, list[tuple[date, date, float]]] = {}
    for s, pe, av, npf in q.iter_rows():
        by_sym.setdefault(s, []).append((pe, av, npf))
    out: dict[date, dict[str, float]] = {}
    for d in decisions:
        got: dict[str, float] = {}
        for s, rows in by_sym.items():
            known = {(pe.year, pe.month): npf for pe, av, npf in rows if av <= d}
            if not known:
                continue
            last = max(pe for pe, av, _ in rows if av <= d)
            if (d - last).days > max_age_days:
                continue
            ks = [_quarter_back(last, k) for k in range(4)]
            if all(k in known for k in ks):
                got[s] = sum(known[k] for k in ks)
        out[d] = got
    return out


def market_caps(filings: pl.DataFrame, panel: pl.DataFrame, decisions: list[date], max_age_days: int
                ) -> dict[date, dict[str, float]]:
    """M144: decision -> symbol -> market cap at d (as in `turnover_ratio`: shares from the latest usable filing,
    carried through later splits and bonuses by adj_factor)."""
    sh = first_share_filings(filings)
    px = panel.select("date", "symbol", "close", "adj_factor").sort("symbol", "date")
    qf = (sh.sort("period_end").join_asof(px.select("symbol", "date", pl.col("adj_factor").alias("af_q")).sort("date"),
                                          left_on="period_end", right_on="date", by="symbol", strategy="backward")
          .drop("date").filter(pl.col("af_q").is_not_null()))
    at_d = px.filter(pl.col("date").is_in(decisions))
    out: dict[date, dict[str, float]] = {}
    for d in decisions:
        usable = (qf.filter((pl.col("avail") <= d) & (pl.col("period_end") >= d - timedelta(days=max_age_days)))
                  .sort("period_end").group_by("symbol").agg(pl.all().last()))
        x = (at_d.filter(pl.col("date") == d).join(usable, on="symbol", how="inner")
             .with_columns((pl.col("shares") * pl.col("close") * pl.col("adj_factor") / pl.col("af_q")).alias("mcap"))
             .filter(pl.col("mcap") > 0.0))
        out[d] = dict(x.select("symbol", "mcap").iter_rows())
    return out
