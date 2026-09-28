"""The two yardsticks every run is shown beside: Nifty 500 TRI buy-and-hold and plain 12-1 momentum.

Both are measured with the same equity-curve metrics as the strategy, over the same period, and the momentum baseline pays
the same slippage and charges. Prices come from the dataset panel cut at `end`, so nothing after the period leaks in.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from mb.config.models import BaselinesConfig, MarketConfig, Momentum
from mb.evaluation.metrics import equity_metrics


def buy_and_hold(root: Path, cfg: BaselinesConfig, start: date, end: date) -> dict[str, Any]:
    tri = pl.read_csv(root / cfg.buy_and_hold.tri_file, try_parse_dates=True).rename({"tri": "equity"})
    return equity_metrics(tri, start, end)


def _rebalance_picks(panel: pl.DataFrame, m: Momentum, start: date, end: date) -> dict[date, list[str]]:
    """Month-end ranking: for each rebalance date, the top_n eligible symbols by momentum."""
    f = (panel.sort("symbol", "date")
         .with_columns(
             adv=pl.col("turnover").rolling_mean(m.adv_window_sessions, min_samples=m.adv_window_sessions).over("symbol"),
             mom=(pl.col("adj_close").shift(m.skip_sessions) / pl.col("adj_close").shift(m.lookback_sessions) - 1.0).over("symbol"))
         .filter(pl.col("date").is_between(start, end)))
    month_ends = (f.select("date").unique().sort("date").with_columns(month=pl.col("date").dt.strftime("%Y-%m"))
                  .group_by("month", maintain_order=True).agg(pl.col("date").max())["date"].to_list())
    picks: dict[date, list[str]] = {}
    for d in month_ends:
        day = f.filter((pl.col("date") == d) & pl.col("series").is_in(m.allowed_series) & (pl.col("close") >= m.min_price_inr)
                       & (pl.col("adv") >= m.min_adv_inr) & pl.col("mom").is_not_null())
        picks[d] = day.sort("mom", "symbol", descending=[True, False]).head(m.top_n)["symbol"].to_list()
    return picks


def momentum(root: Path, cfg: BaselinesConfig, market: MarketConfig, panel_path: Path, start: date, end: date) -> dict[str, Any]:
    m = cfg.momentum
    panel = (pl.scan_parquet(panel_path).filter(pl.col("date") <= end)
             .select("date", "symbol", "series", "close", "turnover", "adj_open", "adj_close").collect())
    picks = _rebalance_picks(panel, m, start, end)
    held_ever = sorted({s for v in picks.values() for s in v})
    days = sorted(panel.filter(pl.col("date").is_between(start, end))["date"].unique().to_list())
    idx = {d: i for i, d in enumerate(days)}
    col = {s: j for j, s in enumerate(held_ever)}
    sub = panel.filter(pl.col("symbol").is_in(held_ever) & pl.col("date").is_between(start, end))
    opn = np.full((len(days), len(held_ever)), np.nan)
    cls = np.full((len(days), len(held_ever)), np.nan)
    for d, s, o, c in sub.select("date", "symbol", "adj_open", "adj_close").iter_rows():
        opn[idx[d], col[s]], cls[idx[d], col[s]] = o, c
    for j in range(cls.shape[1]):  # a delisted or suspended name keeps its last close
        v = cls[:, j]
        ok = ~np.isnan(v)
        last = np.maximum.accumulate(np.where(ok, np.arange(len(v)), -1))
        cls[:, j] = np.where(last >= 0, v[np.maximum(last, 0)], np.nan)

    slip = market.slippage_bps_per_side / 1e4
    buy_f, sell_f = (1 + slip) * (1 + market.buy_charge_rate), (1 - slip) * (1 - market.sell_charge_rate)
    cash, shares = m.initial_capital, np.zeros(len(held_ever))
    target: list[str] | None = None
    rows: list[tuple[date, float, float, int]] = []
    rebalances = 0
    for i, d in enumerate(days):
        if target is not None:
            rebalances += 1
            px = np.where(np.isnan(opn[i]), cls[i], opn[i])  # no open today: a sale uses the last close
            want = np.zeros(len(held_ever))
            for s in target:
                want[col[s]] = 1.0
            equity_open = cash + float(np.nansum(shares * px))
            per_name = equity_open / max(len(target), 1)
            for j in range(len(held_ever)):  # sells first
                cur = shares[j] * px[j] if shares[j] else 0.0
                goal = per_name if want[j] else 0.0
                if cur > goal and not np.isnan(px[j]):
                    n = shares[j] if goal == 0.0 else (cur - goal) / px[j]
                    cash += n * px[j] * sell_f - (market.dp_fee_per_sale_inr if goal == 0.0 else 0.0)
                    shares[j] -= n
            buys = [(j, (per_name - shares[j] * px[j]) if shares[j] else per_name) for j in range(len(held_ever))
                    if want[j] and not np.isnan(opn[i, j]) and (per_name > (shares[j] * px[j] if shares[j] else 0.0))]
            need = sum(v * buy_f for _, v in buys)
            scale = min(1.0, cash / need) if need > 0 else 0.0
            for j, v in buys:
                n = v * scale / opn[i, j]
                cash -= n * opn[i, j] * buy_f
                shares[j] += n
            target = None
        invested = float(np.nansum(shares * cls[i]))
        rows.append((d, cash + invested, invested, int((shares > 0).sum())))
        if d in picks:
            target = picks[d]
    curve = pl.DataFrame(rows, schema=["date", "equity", "invested_value", "open_positions"], orient="row")
    out = equity_metrics(curve, start, end)
    out["rebalances"] = rebalances
    out["avg_open_positions"] = curve["open_positions"].mean()
    return out


def compute(root: Path, cfg: BaselinesConfig, market: MarketConfig, panel_path: Path, start: date, end: date) -> dict[str, Any]:
    return {"nifty500_tri_buy_and_hold": buy_and_hold(root, cfg, start, end),
            "momentum_12_1": momentum(root, cfg, market, panel_path, start, end)}
