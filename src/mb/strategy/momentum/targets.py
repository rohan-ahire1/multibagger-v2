"""Month-end momentum ranking and the target portfolio built from it.

Scores use the adjusted close; the price and turnover filters use the raw columns. Everything is read at the close of the
decision date, and the engine trades at the next session's open.
"""
from __future__ import annotations

from datetime import date

import polars as pl

from mb.engine.rebalance import Target
from mb.strategy.momentum.params import Params, ParamsM8, Ranking, RankingM8, Sizing, Universe


def month_ends(panel: pl.DataFrame, start: date, end: date) -> list[date]:
    days = panel.filter(pl.col("date").is_between(start, end)).select("date").unique().sort("date")
    month = pl.col("date").dt.strftime("%Y-%m").alias("month")
    return days.group_by(month, maintain_order=True).agg(pl.col("date").max())["date"].to_list()


def _score(r: Ranking, lookback: int) -> pl.Expr:
    """The ranking score over `lookback` sessions, per symbol."""
    mom = pl.col("adj_close").shift(r.skip_sessions) / pl.col("adj_close").shift(lookback) - 1.0
    if r.score == "return":
        return mom.over("symbol")
    span = lookback - r.skip_sessions
    vol = (pl.col("adj_close") / pl.col("adj_close").shift(1)).log().rolling_std(span, min_samples=span).shift(r.skip_sessions)
    return (mom / vol).over("symbol")


def ranked(panel: pl.DataFrame, u: Universe, r: Ranking, start: date, end: date) -> dict[date, list[str]]:
    """For each month-end in [start, end], the eligible symbols best first (ties by symbol)."""
    mom = pl.col("adj_close").shift(r.skip_sessions) / pl.col("adj_close").shift(r.lookback_sessions) - 1.0
    cols = [pl.col("turnover").rolling_mean(u.adv_window_sessions, min_samples=u.adv_window_sessions).over("symbol").alias("adv"),
            mom.over("symbol").alias("mom")]
    if r.score == "return_over_vol":
        span = r.lookback_sessions - r.skip_sessions
        vol = (pl.col("adj_close") / pl.col("adj_close").shift(1)).log().rolling_std(span, min_samples=span).shift(r.skip_sessions)
        cols.append(vol.over("symbol").alias("vol"))
    second = r.second_lookback_sessions if isinstance(r, RankingM8) else None
    if second is not None:
        cols.append(_score(r, second).alias("score2"))
    f = panel.sort("symbol", "date").with_columns(cols).filter(pl.col("date").is_between(start, end))
    score = pl.col("mom") / pl.col("vol") if r.score == "return_over_vol" else pl.col("mom")
    f = f.with_columns(score.alias("score"))
    eligible = (pl.col("series").is_in(u.allowed_series) & (pl.col("close") >= u.min_price_inr) & (pl.col("adv") >= u.min_adv_inr)
                & pl.col("score").is_not_null() & pl.col("score").is_finite())
    if second is not None:
        eligible = eligible & pl.col("score2").is_not_null() & pl.col("score2").is_finite()
    if u.exclude_fund_units:
        eligible = eligible & ~pl.col("security_id").str.starts_with("isin:INF")
    out: dict[date, list[str]] = {}
    for d in month_ends(f, start, end):
        day = f.filter((pl.col("date") == d) & eligible)
        if second is not None:  # mean of the two percentile ranks, 1 = best
            # Ranks are summed before dividing so equal means tie exactly and fall back to the symbol order.
            n = pl.len().cast(pl.Float64)
            day = day.with_columns(((pl.col("score").rank("average") + pl.col("score2").rank("average")) / (2.0 * n))
                                   .alias("score"))
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


def vol_gross(panel: pl.DataFrame, s: Sizing, days_per_year: int, dates: list[date]) -> dict[date, float]:
    """min(1, target / the benchmark's annualised realised volatility) at each date. Missing data is an error."""
    assert s.vol_target_annual is not None
    b = (panel.filter(pl.col("symbol") == s.vol_benchmark_symbol).sort("date")
         .with_columns((pl.col("adj_close") / pl.col("adj_close").shift(1)).log()
                       .rolling_std(s.vol_window_sessions, min_samples=s.vol_window_sessions).alias("vol"))
         .filter(pl.col("date").is_in(dates)))
    got = {d: min(1.0, s.vol_target_annual / (v * days_per_year ** 0.5)) for d, v in b.select("date", "vol").iter_rows()
           if v is not None and v > 0.0}
    missing = [d for d in dates if d not in got]
    if missing:
        raise ValueError(f"volatility benchmark {s.vol_benchmark_symbol} has no {s.vol_window_sessions}-session "
                         f"volatility on {missing[:3]}")
    return got


def _pick(order: list[str], keep: list[str], top_n: int, cap: int | None, sectors: dict[str, str]) -> list[str]:
    """Kept names first, then new names in rank order; with a cap, a new name whose industry is full is skipped."""
    pick = list(keep)
    count: dict[str, int] = {}
    for s in keep:
        if s in sectors:
            count[sectors[s]] = count.get(sectors[s], 0) + 1
    for s in order:
        if len(pick) >= top_n:
            break
        if s in keep:
            continue
        sec = sectors.get(s)
        if cap is not None and sec is not None:
            if count.get(sec, 0) >= cap:
                continue
            count[sec] = count.get(sec, 0) + 1
        pick.append(s)
    return pick


def targets(panel: pl.DataFrame, p: Params, start: date, end: date, *, sectors: dict[str, str] | None = None,
            days_per_year: int | None = None) -> dict[date, Target]:
    """`sectors` and `days_per_year` are needed only by the M8 sector cap and volatility target."""
    ranks = ranked(panel, p.universe, p.ranking, start, end)
    regime = risk_on(panel, p.regime.benchmark_symbol, p.regime.sma_sessions, list(ranks)) if p.regime.enabled else {}
    m8 = p if isinstance(p, ParamsM8) else None
    cap = m8.portfolio.max_per_sector if m8 else None
    if cap is not None and sectors is None:
        raise ValueError("max_per_sector needs the sector map")
    scale: dict[date, float] = {}
    if m8 and m8.sizing.vol_target_annual is not None:
        if days_per_year is None:
            raise ValueError("vol_target_annual needs days_per_year")
        scale = vol_gross(panel, m8.sizing, days_per_year, list(ranks))
    resize = m8.portfolio.resize_held if m8 else True
    out: dict[date, Target] = {}
    held: list[str] = []
    for d, order in ranks.items():
        pos = {s: k for k, s in enumerate(order)}
        keep = [s for s in held if s in pos and pos[s] < p.portfolio.hold_rank_max]
        if cap is None:
            pick = keep + [s for s in order if s not in set(keep)][: p.portfolio.top_n - len(keep)]
        else:
            pick = _pick(order, keep, p.portfolio.top_n, cap, sectors or {})
        gross = 1.0 if not p.regime.enabled or regime[d] else p.regime.risk_off_gross
        if scale:
            gross *= scale[d]
        out[d] = Target({s: 1.0 for s in pick}, gross, frozenset() if resize else frozenset(keep))
        held = pick if gross > 0.0 else []
    return out
