"""Month-end momentum ranking and the target portfolio built from it.

Scores use the adjusted close; the price and turnover filters use the raw columns. Everything is read at the close of the
decision date, and the engine trades at the next session's open.
"""
from __future__ import annotations

import dataclasses
import math
from datetime import date

import numpy as np
import polars as pl

from mb.data import insider, market, results
from mb.engine.rebalance import Target
from mb.strategy.momentum.params import (Params, ParamsM8, ParamsM11, ParamsM12, ParamsM19, ParamsM21, ParamsM22, ParamsM46, ParamsM89, ParamsM97, ParamsM99, ParamsM103, ParamsM110, ParamsM111, ParamsM114, ParamsM116, ParamsM117, ParamsM118, ParamsM120, ParamsM121, ParamsM122, ParamsM123, ParamsM124, ParamsM125, ParamsM126, IndustryFilter, Insider, LimitHits, LongReversal, Ranking, RankingM8, RankingM10, RankingM12, RankingM29, RankingM55, ScheduleM57, UniverseM40, UniverseM44, UniverseM53,
                                         Rotation, Sizing, Universe, UniverseM13, VolStates)


def month_ends(panel: pl.DataFrame, start: date, end: date) -> list[date]:
    days = panel.filter(pl.col("date").is_between(start, end)).select("date").unique().sort("date")
    month = pl.col("date").dt.strftime("%Y-%m").alias("month")
    return days.group_by(month, maintain_order=True).agg(pl.col("date").max())["date"].to_list()


def decision_dates(panel: pl.DataFrame, start: date, end: date, offset_sessions: int) -> list[date]:
    """The session `offset_sessions` before each month's last session in [start, end]; a month with fewer is skipped."""
    if offset_sessions == 0:
        return month_ends(panel, start, end)
    days = panel.filter(pl.col("date").is_between(start, end)).select("date").unique().sort("date")
    month = pl.col("date").dt.strftime("%Y-%m").alias("month")
    per_month = days.group_by(month, maintain_order=True).agg(pl.col("date"))["date"].to_list()
    return [m[-1 - offset_sessions] for m in per_month if len(m) > offset_sessions]


def _score(r: Ranking, lookback: int) -> pl.Expr:
    """The ranking score over `lookback` sessions, per symbol."""
    mom = pl.col("adj_close").shift(r.skip_sessions) / pl.col("adj_close").shift(lookback) - 1.0
    if r.score == "return":
        return mom.over("symbol")
    span = lookback - r.skip_sessions
    vol = (pl.col("adj_close") / pl.col("adj_close").shift(1)).log().rolling_std(span, min_samples=span).shift(r.skip_sessions)
    return (mom / vol).over("symbol")


def _log_ret() -> pl.Expr:
    return (pl.col("adj_close") / pl.col("adj_close").shift(1)).log()


def _residual_score(r: RankingM10) -> pl.Expr:
    """Residual momentum, per symbol, from rolling sums of the stock's (y) and benchmark's (x) daily log returns.

    alpha and beta: least squares over `residual_beta_sessions` rows; residuals e = y - alpha - beta x over the last
    lookback - skip of those rows; both windows end `skip_sessions` rows before the row scored. Score = sum(e) / stdev(e).
    """
    assert r.residual_beta_sessions is not None
    big, n = r.residual_beta_sessions, r.lookback_sessions - r.skip_sessions
    x, y = pl.col("_bench_ret"), pl.col("_ret")

    def s(e: pl.Expr, w: int) -> pl.Expr:
        return e.rolling_sum(w, min_samples=w).shift(r.skip_sessions)

    bx, by, bxx, bxy = s(x, big), s(y, big), s(x * x, big), s(x * y, big)
    beta = (big * bxy - bx * by) / (big * bxx - bx * bx)
    alpha = (by - beta * bx) / big
    sx, sy, sxx, syy, sxy = s(x, n), s(y, n), s(x * x, n), s(y * y, n), s(x * y, n)
    sum_e = sy - n * alpha - beta * sx
    sum_e2 = syy + n * alpha ** 2 + beta ** 2 * sxx - 2 * alpha * sy - 2 * beta * sxy + 2 * alpha * beta * sx
    var = (sum_e2 - sum_e ** 2 / n) / (n - 1)
    return (sum_e / var.sqrt()).over("symbol")


def _discreteness(r: Ranking) -> pl.Expr:
    """Information discreteness over the lookback-to-skip span: sign(return) x (share of down days - share of up days)."""
    n = r.lookback_sessions - r.skip_sessions
    ret = pl.col("_ret")

    def share(e: pl.Expr) -> pl.Expr:
        return e.cast(pl.Float64).rolling_sum(n, min_samples=n).shift(r.skip_sessions) / n

    mom = pl.col("adj_close").shift(r.skip_sessions) / pl.col("adj_close").shift(r.lookback_sessions) - 1.0
    return (mom.sign() * (share(ret < 0.0) - share(ret > 0.0))).over("symbol")


def ranked(panel: pl.DataFrame, u: Universe, r: Ranking, start: date, end: date,
           top_n: int | None = None, offset_sessions: int = 0, min_momentum: float | None = None,
           fund_symbols: frozenset[str] | None = None, every_sessions: tuple[int, int] | None = None) -> dict[date, list[str]]:
    """For each month-end in [start, end], the eligible symbols best first (ties by symbol).

    `top_n` is needed only by the M10 frog-in-the-pan option; `offset_sessions` moves the decision date (M11);
    `min_momentum` drops names whose lookback-to-skip return is not above it (M12). `fund_symbols` (M35) are the
    symbols of fund units for `fund_units_by_symbol`; by default those with a fund ISIN in `panel`, which misses every
    fund when the panel ends before mid-2011 (no ISINs in the older bhavcopies). `every_sessions` (M57) = (every, phase):
    decide on the sessions of [start, end] with index = phase mod every instead of at month-ends.
    """
    mom = pl.col("adj_close").shift(r.skip_sessions) / pl.col("adj_close").shift(r.lookback_sessions) - 1.0
    part = r.return_part if isinstance(r, RankingM55) else "total"
    if part != "total":  # M55
        span = r.lookback_sessions - r.skip_sessions
        top, bottom = ("adj_close", "adj_open") if part == "intraday" else ("adj_open", None)
        prev = pl.col("adj_close").shift(1) if bottom is None else pl.col(bottom)
        lr = pl.when((pl.col(top) > 0) & (prev > 0)).then((pl.col(top) / prev).log())
        mom = lr.rolling_sum(span, min_samples=span).shift(r.skip_sessions).exp() - 1.0
    cols = [pl.col("turnover").rolling_mean(u.adv_window_sessions, min_samples=u.adv_window_sessions).over("symbol").alias("adv"),
            mom.over("symbol").alias("mom")]
    if r.score == "return_over_vol":
        span = r.lookback_sessions - r.skip_sessions
        vol = (pl.col("adj_close") / pl.col("adj_close").shift(1)).log().rolling_std(span, min_samples=span).shift(r.skip_sessions)
        cols.append(vol.over("symbol").alias("vol"))
    second = r.second_lookback_sessions if isinstance(r, RankingM8) else None
    if second is not None:
        cols.append(_score(r, second).alias("score2"))
    m10 = r if isinstance(r, RankingM10) else None
    keys: list[str] = []  # M10: sort keys ahead of the usual score (all descending)
    f = panel.sort("symbol", "date")
    if m10 is not None and (m10.residual_beta_sessions is not None or m10.frog_candidates_per_slot is not None):
        f = f.with_columns(_log_ret().over("symbol").alias("_ret"))
    if m10 is not None and m10.high_window_sessions is not None:
        w = m10.high_window_sessions
        cols.append((pl.col("adj_close") / pl.col("adj_high").rolling_max(w, min_samples=w)).over("symbol").alias("near_high"))
        keys.append("near_high")
    if m10 is not None and m10.residual_beta_sessions is not None:
        bench = (panel.filter(pl.col("symbol") == m10.residual_benchmark_symbol)
                 .select("date", pl.col("adj_close").log().alias("_bench_log")))
        if bench.is_empty():
            raise ValueError(f"residual benchmark {m10.residual_benchmark_symbol} is not in the panel")
        f = (f.join(bench, on="date", how="left").sort("symbol", "date")
             .with_columns((pl.col("_bench_log") - pl.col("_bench_log").shift(1)).over("symbol").alias("_bench_ret")))
        cols.append(_residual_score(m10).alias("residual"))
        keys.append("residual")
    frog = m10.frog_candidates_per_slot if m10 is not None else None
    max_frac = r.max_filter_frac if isinstance(r, RankingM12) else None
    if isinstance(r, RankingM12) and max_frac is not None:
        w = r.max_window_sessions
        cols.append((pl.col("adj_close") / pl.col("adj_close").shift(1) - 1.0).rolling_max(w, min_samples=w)
                    .over("symbol").alias("maxret"))
    if frog is not None:
        if top_n is None:
            raise ValueError("frog_candidates_per_slot needs top_n")
        cols.append(_discreteness(r).alias("discreteness"))
    if isinstance(r, RankingM29) and r.order == "htp":
        high = pl.col("adj_close").rolling_max(r.lookback_sessions - r.skip_sessions + 1).shift(r.skip_sessions)
        cols.append((high / pl.col("adj_close").shift(r.lookback_sessions)).log().over("symbol").alias("htp"))
    dfrac = u.delivery_drop_frac if isinstance(u, UniverseM40) else None
    if dfrac is not None:
        span = r.lookback_sessions - r.skip_sessions
        has = pl.col("deliv_qty").is_not_null()
        dq = pl.col("deliv_qty").fill_null(0).cast(pl.Float64).rolling_sum(span, min_samples=span).shift(r.skip_sessions)
        vq = (pl.when(has).then(pl.col("volume")).otherwise(0).cast(pl.Float64).rolling_sum(span, min_samples=span)
              .shift(r.skip_sessions))
        cols.append(pl.when(vq > 0).then(dq / vq).over("symbol").alias("deliv_share"))
        keys_extra = ["deliv_share"]
    else:
        keys_extra = []
    abd = u.abnormal_delivery if isinstance(u, UniverseM53) else None
    if abd is not None:  # M53
        dq0 = pl.col("deliv_qty").fill_null(0).cast(pl.Float64)
        recent = dq0.rolling_sum(abd.recent_sessions, min_samples=abd.recent_sessions) / abd.recent_sessions
        base = (dq0.rolling_sum(abd.base_sessions, min_samples=abd.base_sessions).shift(abd.recent_sessions)
                / abd.base_sessions)
        cols.append(pl.when(base > 0).then(recent / base).over("symbol").alias("abd_ratio"))
        keys_extra.append("abd_ratio")
    max_gap = u.max_gap_days if isinstance(u, UniverseM44) else None
    if max_gap is not None:
        w = r.lookback_sessions
        cols.append((pl.col("date") - pl.col("date").shift(1)).dt.total_days().rolling_max(w, min_samples=w)
                    .over("symbol").alias("max_gap"))
    f = f.with_columns(cols).filter(pl.col("date").is_between(start, end))
    order = r.order if isinstance(r, RankingM29) else "score"
    if order == "low_vol":
        score = -pl.col("vol")
    elif order == "htp":
        score = pl.col("htp") / pl.col("vol") if r.score == "return_over_vol" else pl.col("htp")
    else:
        score = pl.col("mom") / pl.col("vol") if r.score == "return_over_vol" else pl.col("mom")
    f = f.with_columns(score.alias("score"))
    eligible = (pl.col("series").is_in(u.allowed_series) & (pl.col("close") >= u.min_price_inr) & (pl.col("adv") >= u.min_adv_inr)
                & pl.col("score").is_not_null() & pl.col("score").is_finite())
    if second is not None:
        eligible = eligible & pl.col("score2").is_not_null() & pl.col("score2").is_finite()
    if min_momentum is not None:
        eligible = eligible & (pl.col("mom") > min_momentum)
    if max_gap is not None:
        eligible = eligible & (pl.col("max_gap") <= max_gap)
    for k in (keys + (["discreteness"] if frog is not None else []) + (["maxret"] if max_frac is not None else [])
              + keys_extra):
        eligible = eligible & pl.col(k).is_not_null() & pl.col(k).is_finite()
    if u.exclude_fund_units:
        eligible = eligible & ~pl.col("security_id").str.starts_with("isin:INF")
    if isinstance(u, UniverseM13) and u.fund_units_by_symbol:
        funds = (sorted(fund_symbols) if fund_symbols is not None
                 else panel.filter(pl.col("security_id").str.starts_with("isin:INF"))["symbol"].unique().to_list())
        eligible = eligible & ~pl.col("symbol").is_in(pl.Series(funds, dtype=pl.String).implode())
    out: dict[date, list[str]] = {}
    if every_sessions is None:
        dates = decision_dates(f, start, end, offset_sessions)
    else:
        every, phase = every_sessions
        dates = f.select("date").unique().sort("date")["date"].to_list()[phase::every]
    for d in dates:
        day = f.filter((pl.col("date") == d) & eligible)
        if max_frac is not None:
            drop = day.sort("maxret", "symbol", descending=[True, False]).head(math.ceil(max_frac * day.height))["symbol"]
            day = day.filter(~pl.col("symbol").is_in(drop.implode()))
        if dfrac is not None:
            drop = day.sort("deliv_share", "symbol").head(math.ceil(dfrac * day.height))["symbol"]
            day = day.filter(~pl.col("symbol").is_in(drop.implode()))
        if abd is not None:
            drop = day.sort("abd_ratio", "symbol").head(math.ceil(abd.drop_frac * day.height))["symbol"]
            day = day.filter(~pl.col("symbol").is_in(drop.implode()))
        if second is not None:  # mean of the two percentile ranks, 1 = best
            # Ranks are summed before dividing so equal means tie exactly and fall back to the symbol order.
            n = pl.len().cast(pl.Float64)
            day = day.with_columns(((pl.col("score").rank("average") + pl.col("score2").rank("average")) / (2.0 * n))
                                   .alias("score"))
        day = day.sort(*keys, "score", "symbol", descending=[True] * (len(keys) + 1) + [False])
        order = day["symbol"].to_list()
        if frog is not None:
            assert top_n is not None
            k = math.ceil(frog * top_n)
            head = day.head(k).with_row_index("_pos").sort("discreteness", "_pos")["symbol"].to_list()
            order = head + order[k:]
        out[d] = order
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


def banded(panel: pl.DataFrame, symbol: str, sma_sessions: int, band: float, dates: list[date]) -> dict[date, bool]:
    """M103: the filter with a band, walked over the decision dates in order (see RegimeM103)."""
    b = (panel.filter(pl.col("symbol") == symbol).sort("date")
         .with_columns(pl.col("adj_close").rolling_mean(sma_sessions, min_samples=sma_sessions).alias("sma"))
         .filter(pl.col("date").is_in(dates)))
    x = {d: c / s for d, c, s in b.select("date", "adj_close", "sma").iter_rows() if s is not None}
    missing = [d for d in dates if d not in x]
    if missing:
        raise ValueError(f"regime benchmark {symbol} has no close or no {sma_sessions}-session average on {missing[:3]}")
    out: dict[date, bool] = {}
    state: bool | None = None
    for d in sorted(dates):
        state = (x[d] >= 1.0 if state is None else
                 (x[d] >= 1.0 - band) if state else (x[d] > 1.0 + band))
        out[d] = state
    return out


def breadth_on(panel: pl.DataFrame, u: Universe, sma_sessions: int, min_frac: float, dates: list[date],
               fund_symbols: frozenset[str] | None) -> dict[date, bool]:
    """M99: True where at least `min_frac` of the universe's stocks close at or above their own `sma_sessions` average.
    The universe is the ranking's: allowed series, price and liquidity floors, fund units out; a stock counts once it
    has the full average. A date with no such stock is an error."""
    f = (panel.sort("symbol", "date")
         .with_columns(pl.col("turnover").rolling_mean(u.adv_window_sessions, min_samples=u.adv_window_sessions)
                       .over("symbol").alias("adv"),
                       pl.col("adj_close").rolling_mean(sma_sessions, min_samples=sma_sessions).over("symbol").alias("sma"))
         .filter(pl.col("date").is_in(dates)))
    ok = (pl.col("series").is_in(u.allowed_series) & (pl.col("close") >= u.min_price_inr) & (pl.col("adv") >= u.min_adv_inr)
          & pl.col("sma").is_not_null())
    if u.exclude_fund_units:
        ok = ok & ~pl.col("security_id").str.starts_with("isin:INF")
    if isinstance(u, UniverseM13) and u.fund_units_by_symbol:
        funds = (sorted(fund_symbols) if fund_symbols is not None
                 else panel.filter(pl.col("security_id").str.starts_with("isin:INF"))["symbol"].unique().to_list())
        ok = ok & ~pl.col("symbol").is_in(pl.Series(funds, dtype=pl.String).implode())
    share = f.filter(ok).group_by("date").agg((pl.col("adj_close") >= pl.col("sma")).mean().alias("up"))
    got = {d: up >= min_frac for d, up in share.iter_rows()}
    missing = [d for d in dates if d not in got]
    if missing:
        raise ValueError(f"breadth: no eligible stock with a {sma_sessions}-session average on {missing[:3]}")
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


def inverse_vol_weights(panel: pl.DataFrame, sessions: int, picks: dict[date, list[str]]) -> dict[date, dict[str, float]]:
    """1 / stdev of daily log returns over `sessions` rows ending at each date, for the picked names. Missing is an error."""
    names = sorted({s for v in picks.values() for s in v})
    vol = (panel.filter(pl.col("symbol").is_in(names)).sort("symbol", "date")
           .with_columns(_log_ret().rolling_std(sessions, min_samples=sessions).over("symbol").alias("vol"))
           .filter(pl.col("date").is_in(list(picks))))
    got = {(d, s): v for d, s, v in vol.select("date", "symbol", "vol").iter_rows()}
    out: dict[date, dict[str, float]] = {}
    for d, pick in picks.items():
        vs = [got.get((d, s)) for s in pick]
        bad = [s for s, v in zip(pick, vs) if v is None or not v > 0.0]
        if bad:
            raise ValueError(f"no {sessions}-session volatility for {bad[:3]} on {d}")
        out[d] = {s: 1.0 / v for s, v in zip(pick, vs)}
    return out


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
            days_per_year: int | None = None, fund_symbols: frozenset[str] | None = None,
            insider_trades: pl.DataFrame | None = None, meetings: pl.DataFrame | None = None,
            deal_trades: pl.DataFrame | None = None, market_values: pl.DataFrame | None = None,
            industries: pl.DataFrame | None = None) -> dict[date, Target]:
    """`sectors` and `days_per_year` are needed only by the M8 sector cap and volatility target; `fund_symbols` as in `ranked`.
    `insider_trades` (M111, from `mb.data.insider.load`) is needed when `p.insider` is set, `meetings` (M114, from
    `mb.data.results.load`) when `p.results` is set, `deal_trades` (M116, from `mb.data.deals.load`) when `p.deals` is set, `market_values` (M118, from the matching
    `mb.data.market.load_*`) when `p.regime.market_signal` is set."""
    m11 = p if isinstance(p, ParamsM11) else None
    min_mom = p.portfolio.min_momentum if isinstance(p, ParamsM12) else None
    ranks = ranked(panel, p.universe, p.ranking, start, end, p.portfolio.top_n,
                   m11.schedule.decision_offset_sessions if m11 else 0, min_mom, fund_symbols,
                   (m11.schedule.every_sessions, m11.schedule.phase_session)
                   if m11 and isinstance(m11.schedule, ScheduleM57) and m11.schedule.every_sessions is not None else None)
    if isinstance(p, ParamsM46):  # M46: only every n-th month decides
        ranks = {d: o for d, o in ranks.items() if d.month % p.schedule.every_months == p.schedule.phase_month}
    if isinstance(p, ParamsM99) and p.regime.breadth_min_frac is not None:
        regime = breadth_on(panel, p.universe, p.regime.sma_sessions, p.regime.breadth_min_frac, list(ranks), fund_symbols)
    else:
        regime = risk_on(panel, p.regime.benchmark_symbol, p.regime.sma_sessions, list(ranks)) if p.regime.enabled else {}
    if isinstance(p, ParamsM103) and p.regime.band_frac is not None:
        regime = banded(panel, p.regime.benchmark_symbol, p.regime.sma_sessions, p.regime.band_frac, list(ranks))
    if isinstance(p, ParamsM117) and p.regime.risk_off_months:
        regime = seasonal_off(regime, p.regime.risk_off_months)
    ms = p.regime.market_signal if isinstance(p, ParamsM118) else None
    if ms is not None:  # M118: risk-off also when the market signal is off
        if market_values is None:
            raise ValueError("market_signal needs market_values")
        if ms.kind == "vrp":
            assert ms.rv_symbol is not None and ms.rv_sessions is not None
            flag = market.vrp_on(market_values, panel, ms.rv_symbol, ms.rv_sessions, list(ranks))
        else:
            assert ms.window_sessions is not None and ms.min_pct is not None
            flag = market.ranked_on(market_values, list(ranks), ms.window_sessions, ms.min_pct)
        regime = {d: on and flag[d] for d, on in regime.items()}
    st = p.regime.state_sessions if isinstance(p, ParamsM122) else None
    if st is not None:  # M122: risk-off also when the benchmark is below its level st sessions ago
        up = market_state_up(panel, p.regime.benchmark_symbol, st, list(ranks))
        regime = {d: on and up[d] for d, on in regime.items()}
    extra = p.regime.extra_benchmark_symbols if isinstance(p, ParamsM97) else []
    signals = [regime] + [risk_on(panel, b, p.regime.sma_sessions, list(ranks)) for b in extra]
    if isinstance(p, ParamsM126):  # M126: further moving-average lengths on the same benchmark
        signals += [risk_on(panel, p.regime.benchmark_symbol, n, list(ranks)) for n in p.regime.extra_sma_sessions]
    on = {d: sum(r[d] for r in signals) / len(signals) for d in regime}  # M97: share of benchmarks risk-on
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
    tax = p.portfolio if isinstance(p, ParamsM110) and p.portfolio.tax_hold_from_days is not None else None
    since: dict[str, tuple[date, float]] = {}  # M110: held name -> (decision that first picked it, adjusted close then)
    closes = ({(d, s): c for d, s, c in panel.filter(pl.col("date").is_in(list(ranks)))
               .select("date", "symbol", "adj_close").iter_rows()} if tax else {})
    ins = p.insider if isinstance(p, ParamsM111) else None
    if ins is not None and insider_trades is None:
        raise ValueError("insider rule needs insider_trades")
    net = (insider.net_by_decision(insider_trades, list(ranks), ins.lookback_days)
           if ins is not None and insider_trades is not None else {})
    res = p.results if isinstance(p, ParamsM114) else None
    if res is not None:  # M114: the same two rules, on the last results reaction
        if meetings is None:
            raise ValueError("results rule needs meetings")
        net = results.signal_by_decision(results.reactions(meetings, panel, res.benchmark_symbol), meetings,
                                         list(ranks), res.lookback_days)
        ins = Insider(raw_dir=res.raw_dir, categories=[], lookback_days=res.lookback_days,
                      rule="nosell" if res.rule == "noneg" else "buyfirst", rank_max=res.rank_max)
    dl = p.deals if isinstance(p, ParamsM116) else None
    if dl is not None:  # M116: the same two rules, on net bulk and block deal value
        if deal_trades is None:
            raise ValueError("deals rule needs deal_trades")
        net = insider.net_by_decision(deal_trades, list(ranks), dl.lookback_days)
        ins = Insider(raw_dir="", categories=[], lookback_days=dl.lookback_days, rule=dl.rule, rank_max=dl.rank_max)
    lh = p.limit_hits if isinstance(p, ParamsM120) else None
    if lh is not None:  # M120: the nosell rule, on up-limit hits above max_hits
        hits = limit_hits(panel, lh, list(ranks))
        net = {d: {s: -1.0 for s, n in c.items() if n > lh.max_hits} for d, c in hits.items()}
        ins = Insider(raw_dir="", categories=[], lookback_days=lh.sessions, rule="nosell", rank_max=None)
    lr = p.long_reversal if isinstance(p, ParamsM121) else None
    if lr is not None:  # M121: the nosell rule, on the top drop_frac of long-term returns among the ranked names
        net = long_winners(panel, lr, ranks)
        ins = Insider(raw_dir="", categories=[], lookback_days=lr.from_sessions, rule="nosell", rank_max=None)
    ind = p.industry_filter if isinstance(p, ParamsM125) else None
    if ind is not None:  # M125: the nosell rule, on names in the weakest industries (`industries` from nse_industry.load)
        if industries is None:
            raise ValueError("industry_filter needs industries")
        net = weak_industry_names(panel, industries, ind, ranks)
        ins = Insider(raw_dir="", categories=[], lookback_days=ind.lookback_sessions, rule="nosell", rank_max=None)
    sr = p.short_reversal if isinstance(p, ParamsM123) else None
    if sr is not None:  # M123: the nosell rule, on the top drop_frac of recent returns among the ranked names
        net = top_returns(panel, sr.sessions, 0, sr.drop_frac, ranks)
        ins = Insider(raw_dir="", categories=[], lookback_days=sr.sessions, rule="nosell", rank_max=None)
    for d, order in ranks.items():
        pos = {s: k for k, s in enumerate(order)}
        keep = [s for s in held if s in pos and pos[s] < p.portfolio.hold_rank_max]
        if tax:
            assert tax.tax_hold_from_days is not None and tax.tax_hold_until_days is not None
            assert tax.tax_hold_rank_max is not None
            keep += [s for s in held if s not in keep and s in pos and pos[s] < tax.tax_hold_rank_max
                     and tax.tax_hold_from_days <= (d - since[s][0]).days < tax.tax_hold_until_days
                     and closes[(d, s)] > since[s][1]]
        if ins is not None and d in net:
            new = [s for s in order if s not in set(keep)]
            if ins.rule == "nosell":
                new = [s for s in new if net[d].get(s, 0.0) >= 0.0]
            else:
                first = [s for s in new if pos[s] < (ins.rank_max or 0) and net[d].get(s, 0.0) > 0.0]
                new = first + [s for s in new if s not in set(first)]
            pick = keep + new[: p.portfolio.top_n - len(keep)]
        elif cap is None:
            pick = keep + [s for s in order if s not in set(keep)][: p.portfolio.top_n - len(keep)]
        else:
            pick = _pick(order, keep, p.portfolio.top_n, cap, sectors or {})
        gross = 1.0 if not p.regime.enabled else on[d] + (1.0 - on[d]) * p.regime.risk_off_gross
        if scale:
            gross *= scale[d]
        if min_mom is not None:  # each slot stays 1 / top_n; empty slots are cash
            gross *= len(pick) / p.portfolio.top_n
        out[d] = Target({s: 1.0 for s in pick}, gross, frozenset() if resize else frozenset(keep))
        held = pick if gross > 0.0 else []
        if tax:
            since = {s: since[s] if s in since else (d, closes[(d, s)]) for s in held}
    if m11 and m11.portfolio.weighting == "inverse_vol":
        w = inverse_vol_weights(panel, m11.portfolio.inverse_vol_sessions, {d: list(t.weights) for d, t in out.items()})
        out = {d: Target(w[d], t.gross, t.keep_size) for d, t in out.items()}
    if isinstance(p, ParamsM21) and p.exits.book_stop_frac is not None:
        out = book_stops(panel, out, p.exits.book_stop_frac, end)
    if isinstance(p, ParamsM19) and p.portfolio.fixed_weights:
        fixed = p.portfolio.fixed_weights
        n = p.portfolio.fixed_trend_sessions if isinstance(p, ParamsM22) else None
        up = trend_up(panel, sorted(fixed), n, sorted(out)) if n is not None else {}
        out = {d: _with_fixed(t, {s: w for s, w in fixed.items() if n is None or up[(d, s)]}) for d, t in out.items()}
    if isinstance(p, ParamsM89) and p.regime.risk_off_symbol is not None:
        if isinstance(p, ParamsM21) and p.exits.book_stop_frac is not None:
            raise ValueError("risk_off_symbol and book_stop_frac are exclusive")
        out = {d: t if on[d] == 1.0 else with_risk_off(t, p.regime.risk_off_symbol) for d, t in out.items()}
    if isinstance(p, ParamsM124) and p.portfolio.resize_band is not None:
        out = {d: dataclasses.replace(t, resize_band=p.portfolio.resize_band) for d, t in out.items()}
    return out


def limit_hits(panel: pl.DataFrame, lh: LimitHits, dates: list[date]) -> dict[date, dict[str, int]]:
    """M120: per decision date, each symbol's count of up-limit hits (see `LimitHits`) in the last `lh.sessions` sessions."""
    r = pl.col("adj_close") / pl.col("adj_close").shift(1) - 1.0
    near = pl.any_horizontal([r.is_between(b - lh.below, b + lh.above) for b in lh.bands])
    hit = ((pl.col("close") == pl.col("high")) & near).fill_null(False).cast(pl.Int32)
    f = (panel.select("date", "symbol", "close", "high", "adj_close").sort("symbol", "date")
         .with_columns(hit.over("symbol").alias("_hit"))
         .with_columns(pl.col("_hit").rolling_sum(lh.sessions, min_samples=1).over("symbol").alias("hits"))
         .filter(pl.col("date").is_in(dates)))
    out: dict[date, dict[str, int]] = {d: {} for d in dates}
    for d, s, n in f.select("date", "symbol", "hits").iter_rows():
        out[d][s] = n
    return out


def long_winners(panel: pl.DataFrame, lr: LongReversal, ranks: dict[date, list[str]]) -> dict[date, dict[str, float]]:
    """M121: per decision, -1.0 for the ranked names whose long-term return is in the top lr.drop_frac (ties by symbol)."""
    return top_returns(panel, lr.from_sessions, lr.to_sessions, lr.drop_frac, ranks)


def top_returns(panel: pl.DataFrame, from_sessions: int, to_sessions: int, frac: float,
                ranks: dict[date, list[str]]) -> dict[date, dict[str, float]]:
    """M121/M123: per decision, -1.0 for the ranked names whose return from `from_sessions` to `to_sessions` sessions
    before it is in the top `frac` of the ranked names that have one (ties by symbol)."""
    ret = pl.col("adj_close").shift(to_sessions) / pl.col("adj_close").shift(from_sessions) - 1.0
    f = (panel.select("date", "symbol", "adj_close").sort("symbol", "date")
         .with_columns(ret.over("symbol").alias("lt"))
         .filter(pl.col("date").is_in(list(ranks)) & pl.col("lt").is_not_null() & pl.col("lt").is_finite()))
    out: dict[date, dict[str, float]] = {}
    for (d,), g in f.group_by("date"):
        g = g.filter(pl.col("symbol").is_in(ranks[d])).sort("lt", "symbol", descending=[True, False])
        out[d] = {s: -1.0 for s in g.head(math.ceil(frac * g.height))["symbol"].to_list()}
    return {d: out.get(d, {}) for d in ranks}


def weak_industry_names(panel: pl.DataFrame, industries: pl.DataFrame, ind: IndustryFilter,
                        ranks: dict[date, list[str]]) -> dict[date, dict[str, float]]:
    """M125: per decision, -1.0 for the ranked names whose industry (`ind.level`) is in the bottom `ind.drop_frac` of the
    industries with at least `ind.min_members` ranked names, by their members' equal-weighted mean return
    (ties by industry name)."""
    cls = dict(industries.filter(pl.col(ind.level).is_not_null()).select("symbol", ind.level).iter_rows())
    ret = pl.col("adj_close").shift(ind.skip_sessions) / pl.col("adj_close").shift(ind.lookback_sessions) - 1.0
    f = (panel.select("date", "symbol", "adj_close").sort("symbol", "date").with_columns(ret.over("symbol").alias("r"))
         .filter(pl.col("date").is_in(list(ranks)) & pl.col("r").is_not_null() & pl.col("r").is_finite()))
    out: dict[date, dict[str, float]] = {}
    for (d,), g in f.group_by("date"):
        members = g.filter(pl.col("symbol").is_in(ranks[d])).with_columns(
            pl.col("symbol").replace_strict(cls, default=None).alias("cls")).filter(pl.col("cls").is_not_null())
        groups = (members.group_by("cls").agg(pl.col("r").mean(), pl.len().alias("n"))
                  .filter(pl.col("n") >= ind.min_members).sort("r", "cls"))
        weak = set(groups.head(math.ceil(ind.drop_frac * groups.height))["cls"].to_list())
        out[d] = {s: -1.0 for s, c in members.select("symbol", "cls").iter_rows() if c in weak}
    return {d: out.get(d, {}) for d in ranks}


def market_state_up(panel: pl.DataFrame, symbol: str, sessions: int, dates: list[date]) -> dict[date, bool]:
    """M122: True where `symbol`'s adjusted close is at or above its value `sessions` of its sessions earlier. Missing
    data is an error."""
    b = (panel.filter(pl.col("symbol") == symbol).sort("date")
         .with_columns(pl.col("adj_close").shift(sessions).alias("then")).filter(pl.col("date").is_in(dates)))
    got = {d: c >= t for d, c, t in b.select("date", "adj_close", "then").iter_rows() if t is not None}
    missing = [d for d in dates if d not in got]
    if missing:
        raise ValueError(f"market state {symbol} has no close {sessions} sessions back on {missing[:3]}")
    return got


def seasonal_off(regime: dict[date, bool], months: list[int]) -> dict[date, bool]:
    """M117: decisions dated in `months` are risk-off; the rest keep the benchmark's state."""
    return {d: on and d.month not in months for d, on in regime.items()}


def with_risk_off(t: Target, symbol: str) -> Target:
    """M89: the share a risk-off date leaves uninvested (1 - gross) buys `symbol`; the rest keeps its weights."""
    total = sum(t.weights.values())
    w = {s: v / total * t.gross for s, v in t.weights.items()} if total > 0 else {}
    w[symbol] = w.get(symbol, 0.0) + 1.0 - t.gross
    return Target(w, 1.0, t.keep_size)


def trend_up(panel: pl.DataFrame, symbols: list[str], sessions: int, dates: list[date]) -> dict[tuple[date, str], bool]:
    """(date, symbol) -> adjusted close above the close `sessions` rows earlier. Missing data is an error."""
    t = (panel.filter(pl.col("symbol").is_in(symbols)).sort("symbol", "date")
         .with_columns(pl.col("adj_close").shift(sessions).over("symbol").alias("then"))
         .filter(pl.col("date").is_in(dates)))
    got = {(d, s): c > b for d, s, c, b in t.select("date", "symbol", "adj_close", "then").iter_rows() if b is not None}
    missing = [(d, s) for d in dates for s in symbols if (d, s) not in got]
    if missing:
        raise ValueError(f"fixed_trend_sessions: no close or no close {sessions} sessions earlier for {missing[:3]}")
    return got


def book_stops(panel: pl.DataFrame, out: dict[date, Target], frac: float, end: date) -> dict[date, Target]:
    """Add an all-cash target at the first close after a decision where the picks, held from the decision close at their
    target weights, are at or below (1 - frac) x their highest value since then. Missing closes carry the last one."""
    dates = sorted(out)
    names = sorted({s for t in out.values() for s in t.weights})
    wide = (panel.filter(pl.col("symbol").is_in(names) & pl.col("date").is_between(dates[0], end))
            .pivot(on="symbol", index="date", values="adj_close").sort("date"))
    days = wide["date"].to_list()
    at = {d: i for i, d in enumerate(days)}
    px = wide.select([pl.col(s) if s in wide.columns else pl.lit(None, pl.Float64).alias(s) for s in names]).fill_null(
        strategy="forward").to_numpy()
    col = {s: j for j, s in enumerate(names)}
    got = dict(out)
    for k, d in enumerate(dates):
        t = out[d]
        total = sum(t.weights.values())
        if not t.weights or t.gross <= 0.0 or total <= 0.0:
            continue
        stop = at[dates[k + 1]] if k + 1 < len(dates) else len(days)
        i0 = at[d]
        j = [col[s] for s in t.weights]
        base = px[i0, j]
        if np.isnan(base).any():
            raise ValueError(f"book stop: a pick has no close on {d}")
        w = np.array([t.weights[s] / total for s in t.weights]) / base
        path = np.nan_to_num(px[i0 + 1:stop][:, j], nan=0.0) @ w  # a name with no later close keeps its last one
        peak = np.maximum.accumulate(np.concatenate([[1.0], path]))[1:]
        hit = np.flatnonzero(path <= (1.0 - frac) * peak)
        if hit.size and i0 + 1 + hit[0] < stop:
            got[days[i0 + 1 + hit[0]]] = Target({}, t.gross, frozenset())
    return dict(sorted(got.items()))


def _with_fixed(t: Target, fixed: dict[str, float]) -> Target:
    """Fixed symbols at their weight of the invested equity; the picks share the rest in their relative weights."""
    if not fixed:
        return t
    total = sum(t.weights.values())
    rest = 1.0 - sum(fixed.values())
    both = sorted(set(fixed) & set(t.weights))
    if both:
        raise ValueError(f"fixed_weights symbols were also picked: {both}")
    w = {s: v / total * rest for s, v in t.weights.items()} if total > 0 else {}
    return Target(w | fixed, t.gross if w else t.gross * sum(fixed.values()), t.keep_size)


def rotation_shares(shadow: pl.DataFrame, panel: pl.DataFrame, r: Rotation, dates: list[date]) -> dict[date, dict[str, float]]:
    """Per decision date, the share of equity for the book (key "") and for each rotation asset; the rest is cash.

    `shadow` is the shadow book's equity, one row per session (date, equity); its sessions are the calendar. A lookback
    counts sessions on that calendar. An asset's close is carried forward over sessions it did not trade; an asset with no
    close at the date or L sessions earlier is not a candidate for that lookback. Ties go to the book, then asset order.
    """
    cal = shadow.sort("date")
    days = cal["date"].to_list()
    at = {d: i for i, d in enumerate(days)}
    book = cal["equity"].to_numpy()
    wide = (cal.select("date").join(panel.filter(pl.col("symbol").is_in(r.assets)).pivot(on="symbol", index="date", values="adj_close"),
                                    on="date", how="left").sort("date"))
    px = {a: (wide[a].fill_null(strategy="forward").to_numpy() if a in wide.columns else np.full(len(days), np.nan))
          for a in r.assets}
    out: dict[date, dict[str, float]] = {}
    for d in dates:
        if d not in at:
            raise ValueError(f"rotation: decision date {d} is not a session of the shadow book")
        i = at[d]
        share = {k: 0.0 for k in ["", *r.assets]}
        for n in r.lookbacks_sessions:
            if i < n:
                raise ValueError(f"rotation: the shadow book has no equity {n} sessions before {d}")
            cand = [("", book[i] / book[i - n] - 1.0)]
            for a in r.assets:
                now, then = px[a][i], px[a][i - n]
                if np.isfinite(now) and np.isfinite(then) and then > 0.0:
                    cand.append((a, now / then - 1.0))
            for k, ret in sorted(cand, key=lambda c: -c[1])[: r.top_k]:  # stable: ties keep the book, then asset order
                if not r.cash_floor or ret > 0.0:
                    share[k] += 1.0 / r.top_k / len(r.lookbacks_sessions)
        out[d] = share
    return out


def with_rotation(t: Target, share: dict[str, float]) -> Target:
    """The picks scaled to the book's share of `t.gross`, each asset at its share; the rest is cash."""
    both = sorted(set(t.weights) & {a for a in share if a})
    if both:
        raise ValueError(f"rotation assets were also picked: {both}")
    total = sum(t.weights.values())
    book = share[""] * t.gross
    w = {s: v / total * book for s, v in t.weights.items()} if total > 0 and book > 0 else {}
    w |= {a: x for a, x in share.items() if a and x > 0.0}
    gross = sum(w.values())
    return Target(w, gross, t.keep_size) if gross > 0 else Target({}, 0.0, frozenset())


def vol_state_scales(shadow: pl.DataFrame, shadow_targets: dict[date, Target], vs: VolStates,
                     dates: list[date]) -> dict[date, float]:
    """Per decision date, the scale for the picks under conditional volatility targeting (M32).

    `shadow` is the shadow book's equity (date, equity), one row per session; `shadow_targets` its decision dates. The
    volatility at a date is the stdev (ddof 1) of daily log equity returns over the `vol_sessions` sessions to it. A
    shadow decision date counts once its window starts after the shadow's first invested decision. The scale is
    min(1, long-run stdev / that volatility) when the volatility is at or above the `high_quantile` quantile of the counted
    values up to the date (included), else 1. The long-run stdev uses all returns into the sessions from the second
    after the first invested decision up to the date.
    """
    cal = shadow.sort("date")
    days = cal["date"].to_list()
    at = {d: i for i, d in enumerate(days)}
    r = np.diff(np.log(cal["equity"].to_numpy()))  # r[i - 1] is the return into session i
    first = next((d for d in sorted(shadow_targets) if shadow_targets[d].weights and shadow_targets[d].gross > 0), None)
    if first is None:
        raise ValueError("vol_states: the shadow book never invests")
    f = at[first]
    n = vs.vol_sessions

    def vol(i: int) -> float:
        return float(np.std(r[i - n:i], ddof=1))

    counted = [(d, vol(at[d])) for d in sorted(shadow_targets) if d in at and at[d] - n >= f + 1]
    out: dict[date, float] = {}
    for d in dates:
        if d not in at:
            raise ValueError(f"vol_states: decision date {d} is not a session of the shadow book")
        i = at[d]
        hist = [v for e, v in counted if e <= d]
        if len(hist) < vs.min_history_months:
            raise ValueError(f"vol_states: {len(hist)} months of shadow volatility before {d}, need {vs.min_history_months}")
        now = vol(i)
        target = float(np.std(r[f + 1:i], ddof=1))
        out[d] = min(1.0, target / now) if now >= float(np.quantile(hist, vs.high_quantile)) else 1.0
    return out


def with_book_scale(t: Target, k: float, fixed: set[str]) -> Target:
    """The picks' weights times k, the fixed symbols unchanged; the freed share is cash."""
    if k >= 1.0:
        return t
    total = sum(t.weights.values())
    w = {s: (v if s in fixed else v * k) for s, v in t.weights.items()}
    w = {s: v for s, v in w.items() if v > 0.0}
    new = sum(w.values())
    return Target(w, t.gross * new / total, frozenset()) if new > 0.0 and total > 0.0 else Target({}, 0.0, frozenset())
