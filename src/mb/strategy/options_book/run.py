"""Options book runner (M119): F&O stocks ranked by option signals -> month-end equal-weight targets -> rebalance
simulator -> metrics."""
from __future__ import annotations

import bisect
import math
from datetime import date
from pathlib import Path

import polars as pl

from mb.config.loader import Resolved
from mb.data import datasets, fno
from mb.engine.rebalance import RebalanceResult, Target, simulate_targets
from mb.engine.run import score
from mb.evaluation.metrics import exposure_metrics
from mb.runs.record import RunResult
from mb.strategy.momentum.targets import decision_dates
from mb.strategy.options_book.params import Params

__all__ = ["Params", "run", "simulate", "signal_table", "targets"]

SIGNALS = ("call_put_spread", "skew", "option_volume")
BUY_HIGH = {"call_put_spread": True, "skew": False, "option_volume": False}  # the papers' directions


def signal_table(panel: pl.DataFrame, links: pl.DataFrame, p: Params, root: Path, decisions: list[date]) -> pl.DataFrame:
    """date (decision), symbol (panel), and the three signals from the latest F&O session before each decision (NSE
    publishes the F&O bhavcopy in the evening). Rows only for stocks with all three and a bar in allowed_series."""
    s = p.signals
    raw = root / s.raw_dir
    fo_days = sorted(pl.scan_parquet(sorted(raw.glob("*.parquet"))).select("d").unique().collect()["d"].to_list())
    session = {}
    for d in decisions:
        i = bisect.bisect_left(fo_days, d) - 1
        if i < 0:
            raise ValueError(f"no F&O session before {d}")
        session[d] = fo_days[i]
    used = sorted(set(session.values()))
    o = fno.with_iv(fno.chains(raw, used), s.rate_annual, s.min_days_to_expiry)
    cps = fno.call_put_spread(o, s.spread_min_m, s.spread_max_m).rename({"value": "call_put_spread"})
    sk = fno.skew(o, s.skew_put_min_m, s.skew_put_max_m, s.skew_put_target_m,
                  s.skew_call_min_m, s.skew_call_max_m, s.skew_call_target_m).rename({"value": "skew"})
    opt = fno.panel_symbols(fno.option_shares(raw), links)
    opt_sum = fno.window_sum(opt, "sym", "shares", fo_days, s.volume_sessions, used).rename({"at": "d", "shares": "opt"})
    eq = panel.filter(pl.col("series").is_in(p.allowed_series))
    cm_days = sorted(eq["date"].unique().to_list())
    cm_at = {t: cm_days[bisect.bisect_right(cm_days, t) - 1] for t in used}
    stk = fno.window_sum(eq.select(pl.col("date").alias("d"), pl.col("symbol").alias("sym"), pl.col("volume").cast(pl.Float64)),
                         "sym", "volume", cm_days, s.volume_sessions, sorted(set(cm_at.values())))
    stk = (pl.DataFrame({"d": list(cm_at), "at": list(cm_at.values())}).join(stk, on="at").drop("at"))
    ovr = (opt_sum.join(stk, on=["d", "sym"]).filter(pl.col("volume") > 0)
           .select("d", "sym", (pl.col("opt") / pl.col("volume")).alias("option_volume")))
    chain = fno.panel_symbols(cps.join(sk, on=["d", "sym"]), links)
    t = chain.join(ovr, on=["d", "sym"])
    dec = pl.DataFrame({"date": list(session), "d": list(session.values())})
    bars = eq.filter(pl.col("close") > 0).select("date", pl.col("symbol").alias("sym")).unique()
    return (dec.join(t, on="d").join(bars, on=["date", "sym"]).rename({"sym": "symbol"})
            .select("date", "symbol", *SIGNALS).sort("date", "symbol"))


def targets(table: pl.DataFrame, p: Params, decisions: list[date]) -> dict[date, Target]:
    """Equal weight on the best ceil(top_frac x n) of each decision's universe; `combo` is the mean of the three
    percentile ranks oriented so high buys. A decision with an empty universe is an error."""
    sig = p.portfolio.signal
    out: dict[date, Target] = {}
    for d in decisions:
        u = table.filter(pl.col("date") == d)
        if u.is_empty():
            raise ValueError(f"options book: no stocks with all signals on {d}")
        n = u.height
        if sig == "none":
            pick = u["symbol"].to_list()
        else:
            if sig == "combo":
                pct = [((pl.col(c) if BUY_HIGH[c] else -pl.col(c)).rank("average") - 1) / max(n - 1, 1) for c in SIGNALS]
                u = u.with_columns(pl.mean_horizontal(pct).alias("score"))
            else:
                u = u.with_columns((pl.col(sig) if BUY_HIGH[sig] else -pl.col(sig)).alias("score"))
            k = math.ceil(p.portfolio.top_frac * n)
            pick = u.sort(["score", "symbol"], descending=[True, False])["symbol"].head(k).to_list()
        out[d] = Target({s: 1.0 for s in pick}, 1.0)
    return out


def simulate(cfg: Resolved, root: Path) -> tuple[RebalanceResult, pl.DataFrame]:
    """The panel is cut at period.end, so later data cannot leak in. A target on the last session is never traded."""
    p = cfg.params
    assert isinstance(p, Params)
    period = cfg.strategy.period
    path = datasets.dataset_path(root, cfg.strategy.dataset)
    panel = (pl.scan_parquet(path / datasets.PANEL_FILE).filter(pl.col("date") <= period.end)
             .select("date", "symbol", "series", "close", "volume", "adj_open", "adj_close").collect())
    links = pl.read_parquet(path / "rename_links.parquet")
    days = sorted(panel.filter(pl.col("date").is_between(period.start, period.end))["date"].unique().to_list())
    decisions = decision_dates(panel, period.start, period.end, p.decision_offset_sessions)
    table = signal_table(panel, links, p, root, decisions)
    tg = targets(table, p, decisions)
    bars = panel.select("date", "symbol", pl.col("adj_open").alias("open"), pl.col("adj_close").alias("close"))
    return simulate_targets(tg, bars, days, cfg.market, p.initial_capital), table


def run(cfg: Resolved, root: Path) -> RunResult:
    period = cfg.strategy.period
    res, table = simulate(cfg, root)
    fills = res.fills.filter(pl.col("date").is_between(period.start, period.end))
    traded = (fills["shares"] * fills["price"]).sum() if fills.height else 0.0
    exposure = exposure_metrics(res.equity, traded, period.start, period.end)
    sizes = table.group_by("date").len()["len"]
    return score(cfg, root, res.equity, res.holdings, exposure,
                 {"rebalances": res.rebalances, "universe_median": int(sizes.median() or 0), "universe_min": int(sizes.min() or 0)})
