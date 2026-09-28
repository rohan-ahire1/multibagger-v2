"""Month-end momentum ranking and the target portfolio built from it.

Scores use the adjusted close; the price and turnover filters use the raw columns. Everything is read at the close of the
decision date, and the engine trades at the next session's open.
"""
from __future__ import annotations

from datetime import date

import polars as pl

from mb.engine.rebalance import Target
from mb.strategy.momentum.params import Params, Ranking, Universe


def month_ends(panel: pl.DataFrame, start: date, end: date) -> list[date]:
    days = panel.filter(pl.col("date").is_between(start, end)).select("date").unique().sort("date")
    month = pl.col("date").dt.strftime("%Y-%m").alias("month")
    return days.group_by(month, maintain_order=True).agg(pl.col("date").max())["date"].to_list()


def ranked(panel: pl.DataFrame, u: Universe, r: Ranking, start: date, end: date) -> dict[date, list[str]]:
    """For each month-end in [start, end], the eligible symbols best first (ties by symbol)."""
    mom = pl.col("adj_close").shift(r.skip_sessions) / pl.col("adj_close").shift(r.lookback_sessions) - 1.0
    cols = [pl.col("turnover").rolling_mean(u.adv_window_sessions, min_samples=u.adv_window_sessions).over("symbol").alias("adv"),
            mom.over("symbol").alias("mom")]
    if r.score == "return_over_vol":
        span = r.lookback_sessions - r.skip_sessions
        vol = (pl.col("adj_close") / pl.col("adj_close").shift(1)).log().rolling_std(span, min_samples=span).shift(r.skip_sessions)
        cols.append(vol.over("symbol").alias("vol"))
    f = panel.sort("symbol", "date").with_columns(cols).filter(pl.col("date").is_between(start, end))
    score = pl.col("mom") / pl.col("vol") if r.score == "return_over_vol" else pl.col("mom")
    f = f.with_columns(score.alias("score"))
    eligible = (pl.col("series").is_in(u.allowed_series) & (pl.col("close") >= u.min_price_inr) & (pl.col("adv") >= u.min_adv_inr)
                & pl.col("score").is_not_null() & pl.col("score").is_finite())
    if u.exclude_fund_units:
        eligible = eligible & ~pl.col("security_id").str.starts_with("isin:INF")
    out: dict[date, list[str]] = {}
    for d in month_ends(f, start, end):
        day = f.filter((pl.col("date") == d) & eligible)
        out[d] = day.sort("score", "symbol", descending=[True, False])["symbol"].to_list()
    return out


def risk_on(panel: pl.DataFrame, symbol: str, sma_sessions: int, dates: list[date]) -> dict[date, bool]:
    """True where the benchmark's adjusted close is at or above its simple moving average. Missing data is an error."""
    b = (panel.filter(pl.col("symbol") == symbol).sort("date")
         .with_columns(pl.col("adj_close").rolling_mean(sma_sessions, min_samples=sma_sessions).alias("sma"))
         .filter(pl.col("date").is_in(dates)))
    got = {d: (c >= s) for d, c, s in b.select("date", "adj_close", "sma").iter_rows() if s is not None}
    missing = [d for d in dates if d not in got]
    if missing:
        raise ValueError(f"regime benchmark {symbol} has no close or no {sma_sessions}-session average on {missing[:3]}")
    return got


def targets(panel: pl.DataFrame, p: Params, start: date, end: date) -> dict[date, Target]:
    ranks = ranked(panel, p.universe, p.ranking, start, end)
    regime = risk_on(panel, p.regime.benchmark_symbol, p.regime.sma_sessions, list(ranks)) if p.regime.enabled else {}
    out: dict[date, Target] = {}
    held: list[str] = []
    for d, order in ranks.items():
        pos = {s: k for k, s in enumerate(order)}
        keep = [s for s in held if s in pos and pos[s] < p.portfolio.hold_rank_max]
        pick = keep + [s for s in order if s not in set(keep)][: p.portfolio.top_n - len(keep)]
        gross = 1.0 if not p.regime.enabled or regime[d] else p.regime.risk_off_gross
        out[d] = Target({s: 1.0 for s in pick}, gross)
        held = pick if gross > 0.0 else []
    return out
