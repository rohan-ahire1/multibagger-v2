"""Month-end momentum ranking and the target portfolio built from it.

Scores use the adjusted close; the price and turnover filters use the raw columns. Everything is read at the close of the
decision date, and the engine trades at the next session's open.
"""
from __future__ import annotations

import math
from datetime import date

import polars as pl

from mb.engine.rebalance import Target
from mb.strategy.momentum.params import (Params, ParamsM8, ParamsM11, ParamsM12, ParamsM19, Ranking, RankingM8, RankingM10, RankingM12,
                                         Sizing, Universe, UniverseM13)


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
           top_n: int | None = None, offset_sessions: int = 0, min_momentum: float | None = None) -> dict[date, list[str]]:
    """For each month-end in [start, end], the eligible symbols best first (ties by symbol).

    `top_n` is needed only by the M10 frog-in-the-pan option; `offset_sessions` moves the decision date (M11);
    `min_momentum` drops names whose lookback-to-skip return is not above it (M12).
    """
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
    f = f.with_columns(cols).filter(pl.col("date").is_between(start, end))
    score = pl.col("mom") / pl.col("vol") if r.score == "return_over_vol" else pl.col("mom")
    f = f.with_columns(score.alias("score"))
    eligible = (pl.col("series").is_in(u.allowed_series) & (pl.col("close") >= u.min_price_inr) & (pl.col("adv") >= u.min_adv_inr)
                & pl.col("score").is_not_null() & pl.col("score").is_finite())
    if second is not None:
        eligible = eligible & pl.col("score2").is_not_null() & pl.col("score2").is_finite()
    if min_momentum is not None:
        eligible = eligible & (pl.col("mom") > min_momentum)
    for k in keys + (["discreteness"] if frog is not None else []) + (["maxret"] if max_frac is not None else []):
        eligible = eligible & pl.col(k).is_not_null() & pl.col(k).is_finite()
    if u.exclude_fund_units:
        eligible = eligible & ~pl.col("security_id").str.starts_with("isin:INF")
    if isinstance(u, UniverseM13) and u.fund_units_by_symbol:
        funds = panel.filter(pl.col("security_id").str.starts_with("isin:INF"))["symbol"].unique()
        eligible = eligible & ~pl.col("symbol").is_in(funds.implode())
    out: dict[date, list[str]] = {}
    for d in decision_dates(f, start, end, offset_sessions):
        day = f.filter((pl.col("date") == d) & eligible)
        if max_frac is not None:
            drop = day.sort("maxret", "symbol", descending=[True, False]).head(math.ceil(max_frac * day.height))["symbol"]
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
            days_per_year: int | None = None) -> dict[date, Target]:
    """`sectors` and `days_per_year` are needed only by the M8 sector cap and volatility target."""
    m11 = p if isinstance(p, ParamsM11) else None
    min_mom = p.portfolio.min_momentum if isinstance(p, ParamsM12) else None
    ranks = ranked(panel, p.universe, p.ranking, start, end, p.portfolio.top_n,
                   m11.schedule.decision_offset_sessions if m11 else 0, min_mom)
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
        if min_mom is not None:  # each slot stays 1 / top_n; empty slots are cash
            gross *= len(pick) / p.portfolio.top_n
        out[d] = Target({s: 1.0 for s in pick}, gross, frozenset() if resize else frozenset(keep))
        held = pick if gross > 0.0 else []
    if m11 and m11.portfolio.weighting == "inverse_vol":
        w = inverse_vol_weights(panel, m11.portfolio.inverse_vol_sessions, {d: list(t.weights) for d, t in out.items()})
        out = {d: Target(w[d], t.gross, t.keep_size) for d, t in out.items()}
    if isinstance(p, ParamsM19) and p.portfolio.fixed_weights:
        out = {d: _with_fixed(t, p.portfolio.fixed_weights) for d, t in out.items()}
    return out


def _with_fixed(t: Target, fixed: dict[str, float]) -> Target:
    """Fixed symbols at their weight of the invested equity; the picks share the rest in their relative weights."""
    total = sum(t.weights.values())
    rest = 1.0 - sum(fixed.values())
    both = sorted(set(fixed) & set(t.weights))
    if both:
        raise ValueError(f"fixed_weights symbols were also picked: {both}")
    w = {s: v / total * rest for s, v in t.weights.items()} if total > 0 else {}
    return Target(w | fixed, t.gross if w else t.gross * sum(fixed.values()), t.keep_size)
