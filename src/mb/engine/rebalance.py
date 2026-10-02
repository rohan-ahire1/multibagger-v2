"""The rebalance simulator: target weights in, daily equity and holdings out.

A rebalance strategy decides at the close of a decision date which names it wants, their relative weights, and what
fraction of equity to invest (`gross`). The trades happen at the next session's open: sells first, then buys, all buys
scaled down together if cash is short. Prices are the adjusted series. With a stop-loss (M11), a held name that closes at
or below (1 - stop) x its open at the last rebalance session is sold at the next open; the cash waits for the next
rebalance, or with `stop_to` (M75) buys that symbol at the same open (it is never stopped itself). M76: with
`stop_trail` the reference ratchets up to the highest close since the rebalance; with `stop_vol` = (n, k) a name's stop is
max(stop, k x the std of its last n daily close returns up to the decision close). M79: with `stop_market` = (symbol,
g) stops fire only while that symbol closes at or below (1 - g) x its open at the last rebalance session. A name with no open that session is
not bought and is sold at its last close; a name that stops trading is valued at its last close until it is sold.

The 12-1 momentum baseline and every rebalance strategy run through this one function.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from mb.config.models import MarketConfig

HOLDING_SCHEMA = {
    "symbol": pl.String, "entry_date": pl.Date, "exit_date": pl.Date, "bought": pl.Float64, "sold": pl.Float64,
    "pnl": pl.Float64, "return_pct": pl.Float64, "r_multiple": pl.Float64, "holding_days": pl.Int64, "status": pl.String,
}
FILL_SCHEMA = {"date": pl.Date, "symbol": pl.String, "side": pl.String, "shares": pl.Float64, "price": pl.Float64,
               "cash_flow": pl.Float64}
EQUITY_SCHEMA = {"date": pl.Date, "equity": pl.Float64, "cash": pl.Float64, "invested_value": pl.Float64,
                 "open_positions": pl.Int64}


@dataclass(frozen=True)
class Target:
    weights: dict[str, float]  # relative weights, normalised by their sum
    gross: float               # fraction of equity to invest; the rest stays in cash
    keep_size: frozenset[str] = frozenset()  # wanted names already held are left as they are, not resized to their goal


@dataclass
class RebalanceResult:
    equity: pl.DataFrame     # one row per session
    holdings: pl.DataFrame   # one row per continuous holding of a name (a "trade"); P&L is net of costs
    fills: pl.DataFrame      # every buy and sell, cash_flow net of costs (negative for buys)
    rebalances: int


def simulate_targets(targets: dict[date, Target], bars: pl.DataFrame, days: list[date], market: MarketConfig,
                     initial_capital: float, stop_loss_frac: float | None = None, stop_to: str | None = None,
                     stop_trail: bool = False, stop_vol: tuple[int, float] | None = None,
                     stop_market: tuple[str, float] | None = None) -> RebalanceResult:
    """`bars` has date, symbol, open, close (adjusted) for every name any target mentions; `days` is the session calendar.

    A target dated on a session is traded at the next session's open.
    """
    names = sorted({s for t in targets.values() for s in t.weights})
    idx = {d: i for i, d in enumerate(days)}
    col = {s: j for j, s in enumerate(names)}
    opn = np.full((len(days), len(names)), np.nan)
    cls = np.full((len(days), len(names)), np.nan)
    sub = bars.filter(pl.col("symbol").is_in(names) & pl.col("date").is_in(days))
    for d, s, o, c in sub.select("date", "symbol", "open", "close").iter_rows():
        opn[idx[d], col[s]], cls[idx[d], col[s]] = o, c
    if stop_to is not None and (stop_loss_frac is None or stop_to not in col):
        raise ValueError(f"stop_to {stop_to} needs a stop and must be in every target's names")
    park = col[stop_to] if stop_to is not None else -1
    if (stop_trail or stop_vol is not None or stop_market is not None) and stop_loss_frac is None:
        raise ValueError("stop_trail, stop_vol and stop_market need a stop")
    if stop_market is not None:
        mkt = bars.filter((pl.col("symbol") == stop_market[0]) & pl.col("date").is_in(days))
        if mkt.is_empty():
            raise ValueError(f"stop_market symbol {stop_market[0]} has no bars")
        mo, mc = np.full(len(days), np.nan), np.full(len(days), np.nan)
        for d, o, c in mkt.select("date", "open", "close").iter_rows():
            mo[idx[d]], mc[idx[d]] = o, c
        last = np.maximum.accumulate(np.where(~np.isnan(mc), np.arange(len(mc)), -1))
        mc = np.where(last >= 0, mc[np.maximum(last, 0)], np.nan)
    mref = np.nan
    for j in range(cls.shape[1]):  # a delisted or suspended name keeps its last close
        v = cls[:, j]
        ok = ~np.isnan(v)
        last = np.maximum.accumulate(np.where(ok, np.arange(len(v)), -1))
        cls[:, j] = np.where(last >= 0, v[np.maximum(last, 0)], np.nan)

    slip = market.slippage_bps_per_side / 1e4
    buy_f, sell_f = (1 + slip) * (1 + market.buy_charge_rate), (1 - slip) * (1 - market.sell_charge_rate)
    daily_yield = market.idle_cash_yield_annual / market.trading_days_per_year
    cash, shares = initial_capital, np.zeros(len(names))
    opened: list[date | None] = [None] * len(names)
    bought, sold = np.zeros(len(names)), np.zeros(len(names))
    holdings: list[dict] = []
    fills: list[tuple] = []
    rows: list[tuple[date, float, float, float, int]] = []
    pending: Target | None = None
    rebalances = 0
    ref = np.full(len(names), np.nan)  # stop reference: the open at the last rebalance session
    frac = np.full(len(names), stop_loss_frac if stop_loss_frac is not None else np.nan)  # each name's stop
    stops: list[int] = []              # names whose stop fired at the last close; sold at this open

    def close_holding(j: int, day: date, status: str, mark: float = 0.0) -> None:
        pnl = sold[j] + mark - bought[j]
        holdings.append({"symbol": names[j], "entry_date": opened[j], "exit_date": day, "bought": bought[j],
                         "sold": sold[j] + mark, "pnl": pnl, "return_pct": pnl / bought[j] * 100.0 if bought[j] else None,
                         "r_multiple": None, "holding_days": (day - opened[j]).days, "status": status})
        opened[j], bought[j], sold[j] = None, 0.0, 0.0

    for i, d in enumerate(days):
        if daily_yield and cash > 0.0:
            cash += cash * daily_yield
        if pending is not None:
            rebalances += 1
            px = np.where(np.isnan(opn[i]), cls[i], opn[i])  # no open today: a sale uses the last close
            want = np.zeros(len(names), dtype=bool)
            goal = np.zeros(len(names))
            equity_open = cash + float(np.nansum(shares * px))
            total = sum(pending.weights.values())
            for s, w in pending.weights.items():
                want[col[s]] = True
                goal[col[s]] = equity_open * pending.gross * w / total if total > 0 else 0.0
                if s in pending.keep_size and shares[col[s]]:
                    goal[col[s]] = shares[col[s]] * px[col[s]]
            for j in range(len(names)):  # sells first
                cur = shares[j] * px[j] if shares[j] else 0.0
                g = goal[j] if want[j] else 0.0
                if cur > g and not np.isnan(px[j]):
                    n = shares[j] if g == 0.0 else (cur - g) / px[j]
                    flow = n * px[j] * sell_f - (market.dp_fee_per_sale_inr if g == 0.0 else 0.0)
                    cash += flow
                    shares[j] -= n
                    sold[j] += flow
                    fills.append((d, names[j], "sell", n, px[j], flow))
                    if shares[j] == 0.0:
                        close_holding(j, d, "rebalanced_out")
            # Top-ups stay numpy floats and new names are Python floats: sum() compensates only while it sees Python floats,
            # and this mix reproduces the pinned momentum baseline bit for bit.
            buys = [(j, (goal[j] - shares[j] * px[j]) if shares[j] else float(goal[j])) for j in range(len(names))
                    if want[j] and not np.isnan(opn[i, j]) and (goal[j] > (shares[j] * px[j] if shares[j] else 0.0))]
            need = sum(v * buy_f for _, v in buys)
            scale = min(1.0, cash / need) if need > 0 else 0.0
            for j, v in buys:
                n = v * scale / opn[i, j]
                flow = n * opn[i, j] * buy_f
                cash -= flow
                if opened[j] is None:
                    opened[j] = d
                shares[j] += n
                bought[j] += flow
                fills.append((d, names[j], "buy", n, opn[i, j], -flow))
            pending = None
            stops = []
            if stop_loss_frac is not None:
                ref = np.where(shares > 0.0, px, np.nan)
                if stop_market is not None:
                    mref = mo[i] if not np.isnan(mo[i]) else mc[i]
                if stop_vol is not None:
                    n_vol, k_vol = stop_vol
                    win = cls[max(i - n_vol - 1, 0):i]
                    with np.errstate(invalid="ignore", divide="ignore"):
                        r = win[1:] / win[:-1] - 1.0
                    ok = (~np.isnan(r)).sum(axis=0) == n_vol
                    sd = np.where(ok, np.nanstd(np.where(np.isnan(r), 0.0, r), axis=0, ddof=1), 0.0)
                    frac = np.maximum(stop_loss_frac, k_vol * sd)
        elif stops:
            px = np.where(np.isnan(opn[i]), cls[i], opn[i])
            freed = 0.0
            for j in stops:
                n = shares[j]
                flow = n * px[j] * sell_f - market.dp_fee_per_sale_inr
                cash += flow
                shares[j] = 0.0
                sold[j] += flow
                fills.append((d, names[j], "sell", n, px[j], flow))
                close_holding(j, d, "stopped")
                freed += flow
            if park >= 0 and freed > 0.0 and not np.isnan(opn[i, park]):
                v = min(freed, cash)
                n = v / (opn[i, park] * buy_f)
                cash -= v
                if opened[park] is None:
                    opened[park] = d
                shares[park] += n
                bought[park] += v
                fills.append((d, names[park], "buy", n, opn[i, park], -v))
            stops = []
        invested = float(np.nansum(shares * cls[i]))
        rows.append((d, cash + invested, cash, invested, int((shares > 0).sum())))
        if d in targets:
            pending = targets[d]
        elif stop_loss_frac is not None:
            if stop_trail:
                ref = np.where(shares > 0.0, np.fmax(ref, cls[i]), ref)
            stops = [j for j in np.flatnonzero(shares > 0.0) if j != park and cls[i, j] <= ref[j] * (1.0 - frac[j])]
            if stop_market is not None and not mc[i] <= mref * (1.0 - stop_market[1]):
                stops = []

    for j in range(len(names)):
        if opened[j] is not None:
            close_holding(j, days[-1], "open", mark=float(shares[j] * cls[-1, j]))
    return RebalanceResult(
        equity=pl.DataFrame(rows, schema=EQUITY_SCHEMA, orient="row"),
        holdings=pl.from_dicts(holdings, schema=HOLDING_SCHEMA).sort("entry_date", "symbol"),
        fills=pl.DataFrame(fills, schema=FILL_SCHEMA, orient="row"),
        rebalances=rebalances,
    )
