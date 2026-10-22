"""Replay: the backtest over the paper period on today's dataset, compared with what the paper book did.

The picks at every month-end must match exactly (and the weights, for a book that records them). Equity will differ a little (whole shares, orders sized off the close,
fills of the rounded share counts), and the gap is reported and alerted on above the configured limit.

A cash adjustment (dividend, or a demerger the feed gives no new listing for) is cash in the paper book, but the
backtest's adjusted prices reinvest it in the same name until its next month-end. That part of the gap is estimated
from the raw closes and taken out before the limit is checked (a demerged stub on a run of upper circuits once moved
the raw gap 2%).
"""
from __future__ import annotations

import math
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

    # Picks are recorded under the symbols of their day; a later rename in this dataset relabels them.
    paper = {(dt := date.fromisoformat(d["session"])): (sorted(view.renamed(k, dt) for k in d["decision"]["picks"]),
                                                        d["decision"]["gross"]) for d in days if d["decision"]}
    weights = {(dt := date.fromisoformat(d["session"])): {view.renamed(k, dt): w for k, w in d["decision"]["weights"].items()}
               for d in days if d["decision"] and "weights" in d["decision"]}
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
        elif d in weights:
            t = tg[d].weights
            total = sum(t.values())
            off = {k: [w, t[k] / total] for k, w in weights[d].items() if not math.isclose(w, t[k] / total, rel_tol=1e-9)}
            if off:
                mismatches.append({"date": d.isoformat(), "weights": off})
    bt_eq = dict(zip(sim.equity["date"].to_list(), sim.equity["equity"].to_list()))
    drift = _reinvested(days, cut, bt_eq)
    raw = [(d["session"], (d["equity"] / bt_eq[date.fromisoformat(d["session"])] - 1) * 100) for d in days
           if date.fromisoformat(d["session"]) in bt_eq]
    gaps = [(d["session"], ((d["equity"] + drift[d["session"]]) / bt_eq[date.fromisoformat(d["session"])] - 1) * 100)
            for d in days if date.fromisoformat(d["session"]) in bt_eq]
    last_gap = gaps[-1][1] if gaps else 0.0
    worst = max(gaps, key=lambda g: abs(g[1])) if gaps else (None, 0.0)
    return {
        "as_of": as_of.isoformat(), "dataset": view.ref, "decisions_paper": len(paper), "decisions_backtest": len(bt),
        "decision_mismatches": mismatches, "paper_equity": days[-1]["equity"], "backtest_equity": bt_eq.get(as_of),
        "raw_equity_gap_pct": raw[-1][1] if raw else 0.0, "reinvested_cash": drift[days[-1]["session"]],
        "equity_gap_pct": last_gap, "worst_equity_gap_pct": worst[1], "worst_equity_gap_date": worst[0],
        "ok": not mismatches and abs(last_gap) <= cfg.replay_max_equity_gap_pct,
    }


def _reinvested(days: list[dict[str, Any]], panel: pl.DataFrame, bt_eq: dict[date, float]) -> dict[str, float]:
    """Per session, how much more the backtest holds because it reinvested the paper book's cash adjustments.

    For cash C paid at p per share on a name that closed at pc the session before, the backtest holds C / (pc - p)
    more shares; they are worth that times today's raw close, less C. At the next month-end the backtest resizes
    everything to its targets, so from then on the amount is kept as a share of the backtest's equity.
    """
    close = {(r[0], r[1]): r[2] for r in panel.select("date", "symbol", "close").iter_rows()}
    out: dict[str, float] = {}
    live: list[list] = []  # [symbol, extra shares, cash, value at freeze or None]
    frozen = 0.0  # share of backtest equity
    prev: dict[str, float] = {}
    for d in days:
        s = date.fromisoformat(d["session"])
        for c in d["corporate_actions"]:
            if c["kind"] == "cash_adjustment" and c["cash"] > 0 and c["symbol"] in prev and prev[c["symbol"]] > c["per_share"]:
                live.append([c["symbol"], c["cash"] / (prev[c["symbol"]] - c["per_share"]), c["cash"], 0.0])
        for x in live:
            px = close.get((s, x[0]))
            if px is not None:
                x[3] = x[1] * px - x[2]
        eq = bt_eq.get(s)
        out[d["session"]] = (frozen * eq if eq else 0.0) + sum(x[3] for x in live)
        if d["decision"] and eq:
            frozen, live = out[d["session"]] / eq, []
        prev = {p["symbol"]: p["close"] for p in d["positions"]}
    return out


def report(r: dict[str, Any]) -> str:
    lines = [f"# Replay through {r['as_of']}", "", f"- Dataset: `{r['dataset']}`",
             f"- Month-end decisions: paper {r['decisions_paper']}, backtest {r['decisions_backtest']}, "
             f"mismatched {len(r['decision_mismatches'])}",
             f"- Equity: paper ₹{r['paper_equity']:,.0f}, backtest ₹{r['backtest_equity'] or 0:,.0f}, "
             f"gap {r['equity_gap_pct']:+.3f}% (worst {r['worst_equity_gap_pct']:+.3f}% on {r['worst_equity_gap_date']})",
             f"- Raw gap {r.get('raw_equity_gap_pct', r['equity_gap_pct']):+.3f}%, of which cash adjustments the backtest "
             f"reinvests ₹{r.get('reinvested_cash', 0.0):,.0f}",
             f"- Verdict: {'match' if r['ok'] else 'MISMATCH'}"]
    for m in r["decision_mismatches"]:
        lines.append(f"  - {m}")
    return "\n".join(lines) + "\n"
