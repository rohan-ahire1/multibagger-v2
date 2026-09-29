"""Replay: the backtest over the paper period on today's dataset, compared with what the paper book did.

The picks at every month-end must match exactly. Equity will differ a little (whole shares, orders sized off the close,
fills of the rounded share counts), and the gap is reported and alerted on above the configured limit.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from mb.config.loader import Resolved
from mb.config.models import PaperConfig
from mb.engine.rebalance import simulate_targets
from mb.live.paper import DataView
from mb.strategy.momentum.params import Params
from mb.strategy.momentum.targets import targets


def replay(cfg: PaperConfig, strat: Resolved, view: DataView, days: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not days:
        return None
    p = strat.params
    assert isinstance(p, Params)
    as_of = date.fromisoformat(days[-1]["session"])
    cut = view.panel.filter(pl.col("date") <= as_of)
    sessions = sorted(cut.filter(pl.col("date") >= cfg.start)["date"].unique().to_list())
    tg = targets(cut, p, cfg.start, as_of)
    bars = cut.select("date", "symbol", pl.col("adj_open").alias("open"), pl.col("adj_close").alias("close"))
    sim = simulate_targets(tg, bars, sessions, strat.market, cfg.initial_capital)

    paper = {date.fromisoformat(d["session"]): (d["decision"]["picks"], d["decision"]["gross"]) for d in days if d["decision"]}
    # The backtest treats the last session as a month-end; that is only a decision if the book made one there.
    bt = {d: (sorted(t.weights), t.gross) for d, t in tg.items() if d != as_of or d in paper}
    mismatches = []
    for d in sorted(set(paper) | set(bt)):
        a, b = paper.get(d), bt.get(d)
        if a is None or b is None:
            mismatches.append({"date": d.isoformat(), "paper": a, "backtest": b})
        elif a != b:
            mismatches.append({"date": d.isoformat(), "paper_only": sorted(set(a[0]) - set(b[0])),
                               "backtest_only": sorted(set(b[0]) - set(a[0])), "gross": [a[1], b[1]]})
    bt_eq = dict(zip(sim.equity["date"].to_list(), sim.equity["equity"].to_list()))
    gaps = [(d["session"], (d["equity"] / bt_eq[date.fromisoformat(d["session"])] - 1) * 100) for d in days
            if date.fromisoformat(d["session"]) in bt_eq]
    last_gap = gaps[-1][1] if gaps else 0.0
    worst = max(gaps, key=lambda g: abs(g[1])) if gaps else (None, 0.0)
    return {
        "as_of": as_of.isoformat(), "dataset": view.ref, "decisions_paper": len(paper), "decisions_backtest": len(bt),
        "decision_mismatches": mismatches, "paper_equity": days[-1]["equity"], "backtest_equity": bt_eq.get(as_of),
        "equity_gap_pct": last_gap, "worst_equity_gap_pct": worst[1], "worst_equity_gap_date": worst[0],
        "ok": not mismatches and abs(last_gap) <= cfg.replay_max_equity_gap_pct,
    }


def report(r: dict[str, Any]) -> str:
    lines = [f"# Replay through {r['as_of']}", "", f"- Dataset: `{r['dataset']}`",
             f"- Month-end decisions: paper {r['decisions_paper']}, backtest {r['decisions_backtest']}, "
             f"mismatched {len(r['decision_mismatches'])}",
             f"- Equity: paper ₹{r['paper_equity']:,.0f}, backtest ₹{r['backtest_equity'] or 0:,.0f}, "
             f"gap {r['equity_gap_pct']:+.3f}% (worst {r['worst_equity_gap_pct']:+.3f}% on {r['worst_equity_gap_date']})",
             f"- Verdict: {'match' if r['ok'] else 'MISMATCH'}"]
    for m in r["decision_mismatches"]:
        lines.append(f"  - {m}")
    return "\n".join(lines) + "\n"
