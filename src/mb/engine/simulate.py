"""The one portfolio simulator.

Signals in, fills/exits/sizing/costs handled here, trades and a daily equity curve out. It never looks past
the current session: a signal made at the close of D can fill from the symbol's next session; a close-confirmed
exit fills at the next session's open; a stop is checked against the range of the session that hits it.

Prices are the panel's adjusted series (`adj_*`), passed in as open/high/low/close.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import polars as pl

from mb.config.models import MarketConfig
from mb.engine.config import EngineConfig, EntryRulesVCP, ExitRulesVCP

SIGNAL_COLUMNS = ("symbol", "signal_date", "entry_ref", "stop", "size_mult")
BAR_COLUMNS = ("date", "symbol", "open", "high", "low", "close")
MIN_SHARES = 1e-5

TRADE_SCHEMA = {
    "symbol": pl.String, "signal_date": pl.Date, "entry_date": pl.Date, "entry_price": pl.Float64,
    "stop": pl.Float64, "exit_date": pl.Date, "exit_price": pl.Float64, "shares": pl.Float64,
    "return_pct": pl.Float64, "r_multiple": pl.Float64, "pnl": pl.Float64, "status": pl.String,
    "holding_days": pl.Int64, "mae_r": pl.Float64, "mfe_r": pl.Float64, "sector": pl.String,
    "entry_ref": pl.Float64,
}
EQUITY_SCHEMA = {
    "date": pl.Date, "equity": pl.Float64, "cash": pl.Float64, "invested_value": pl.Float64,
    "open_positions": pl.Int64, "size_mult": pl.Float64,
}
SKIPPED_SCHEMA = {"symbol": pl.String, "signal_date": pl.Date, "status": pl.String}


@dataclass
class SimResult:
    trades: pl.DataFrame     # filled trades only
    equity: pl.DataFrame     # one row per session
    skipped: pl.DataFrame    # signals that never filled, with the reason


@dataclass
class _Series:
    dates: list[date]
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]
    index: dict[date, int]
    ema10: list[float]
    ema21: list[float]
    sma: list[float]      # the SMA trail's average; empty unless the exit mode is "sma"


@dataclass
class _Pending:
    symbol: str
    signal_date: date
    entry_ref: float
    stop: float
    size_mult: float
    bars_checked: int = 0


@dataclass
class _Position:
    symbol: str
    signal_date: date
    entry_ref: float
    stop: float
    entry_date: date
    entry_price: float
    shares: float
    active_stop: float
    initial_risk: float
    mae_price: float
    mfe_price: float
    breakeven: bool = False
    bars_held: int = 0
    pending_exit: str | None = None


def _ema(values: list[float], span: int) -> list[float]:
    """Exponential average seeded with the simple average of the first `span` values; 0.0 before that."""
    out = [0.0] * len(values)
    if len(values) < span:
        return out
    out[span - 1] = sum(values[:span]) / span
    k = 2.0 / (span + 1.0)
    for i in range(span, len(values)):
        out[i] = (values[i] - out[i - 1]) * k + out[i - 1]
    return out


def _sma(values: list[float], span: int) -> list[float]:
    """Simple average of the last `span` values; 0.0 before that."""
    out = [0.0] * len(values)
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= span:
            run -= values[i - span]
        if i >= span - 1:
            out[i] = run / span
    return out


def _build_series(bars: pl.DataFrame, symbols: set[str], sma_span: int | None) -> dict[str, _Series]:
    out: dict[str, _Series] = {}
    sub = bars.filter(pl.col("symbol").is_in(list(symbols))).sort("symbol", "date")
    for g in sub.partition_by("symbol", maintain_order=True):
        dates = g["date"].to_list()
        close = g["close"].to_list()
        out[str(g["symbol"][0])] = _Series(
            dates=dates, open=g["open"].to_list(), high=g["high"].to_list(), low=g["low"].to_list(),
            close=close, index={d: i for i, d in enumerate(dates)}, ema10=_ema(close, 10), ema21=_ema(close, 21),
            sma=_sma(close, sma_span) if sma_span else [],
        )
    return out


def _check_inputs(signals: pl.DataFrame, bars: pl.DataFrame) -> None:
    for name, frame, cols in (("signals", signals, SIGNAL_COLUMNS), ("bars", bars, BAR_COLUMNS)):
        missing = [c for c in cols if c not in frame.columns]
        if missing:
            raise ValueError(f"{name} frame is missing columns: {missing}")
    if bars.is_empty():
        raise ValueError("bars frame is empty")


@dataclass
class _Costs:
    """Slippage and statutory charges as separate multipliers, applied in that order (float rounding matters:
    fills are sized against cash, and a one-ulp difference can flip a fill)."""
    slip_buy: float
    slip_sell: float
    charge_buy: float
    charge_sell: float
    dp_fee: float

    @classmethod
    def from_market(cls, m: MarketConfig) -> _Costs:
        slip = m.slippage_bps_per_side / 10_000.0
        return cls(1.0 + slip, 1.0 - slip, 1.0 + m.buy_charge_rate, 1.0 - m.sell_charge_rate, m.dp_fee_per_sale_inr)

    def buy(self, price: float) -> float:
        return price * self.slip_buy * self.charge_buy

    def sell(self, price: float) -> float:
        return price * self.slip_sell * self.charge_sell


@dataclass
class _Book:
    cash: float
    peak: float
    positions: list[_Position] = field(default_factory=list)
    pending: list[_Pending] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


def simulate(signals: pl.DataFrame, bars: pl.DataFrame, sectors: dict[str, str],
             eng: EngineConfig, market: MarketConfig) -> SimResult:
    _check_inputs(signals, bars)
    costs = _Costs.from_market(market)
    ex, sz, br, en = eng.exits, eng.sizing, eng.breaker, eng.entry
    if not (br.half_dd <= br.stop_dd <= br.close_dd):
        raise ValueError("breaker thresholds must satisfy half_dd <= stop_dd <= close_dd")

    sig_rows = signals.sort("signal_date", "symbol").to_dicts()
    vcp_entry = en if isinstance(en, EntryRulesVCP) else None
    sma_span = ex.trail_sma_sessions if isinstance(ex, ExitRulesVCP) and ex.mode == "sma" else None
    series = _build_series(bars, {r["symbol"] for r in sig_rows}, sma_span)
    calendar = sorted(bars["date"].unique().to_list())
    by_day: dict[date, list[dict]] = defaultdict(list)
    for r in sig_rows:
        by_day[r["signal_date"]].append(r)

    daily_yield = market.idle_cash_yield_annual / market.trading_days_per_year
    book = _Book(cash=eng.initial_capital, peak=eng.initial_capital)
    equity_rows: list[dict] = []

    def sector_of(sym: str) -> str:
        return sectors.get(sym, sz.default_sector)

    def capped(sector: str) -> bool:
        return sector not in sz.uncapped_sectors

    def close_out(pos: _Position, day: date, raw_exit: float, status: str) -> None:
        net_entry = costs.buy(pos.entry_price)
        net_exit = costs.sell(raw_exit)
        book.cash += pos.shares * net_exit - costs.dp_fee
        net_stop = costs.sell(pos.stop)
        risk = net_entry - net_stop
        pnl = pos.shares * (net_exit - net_entry) - costs.dp_fee
        book.trades.append({
            "symbol": pos.symbol, "signal_date": pos.signal_date, "entry_date": pos.entry_date,
            "entry_price": net_entry, "stop": pos.stop, "exit_date": day, "exit_price": net_exit,
            "shares": pos.shares,
            "return_pct": pnl / (pos.shares * net_entry) * 100.0 if pos.shares > MIN_SHARES else None,
            "r_multiple": pnl / (pos.shares * risk) if risk > 0.0 and pos.shares > MIN_SHARES else None,
            "pnl": pnl, "status": status, "holding_days": (day - pos.entry_date).days,
            "mae_r": (pos.mae_price - net_entry) / risk if risk > 0.0 else None,
            "mfe_r": (pos.mfe_price - net_entry) / risk if risk > 0.0 else None,
            "sector": sector_of(pos.symbol), "entry_ref": pos.entry_ref,
        })

    def session_stop(pos: _Position) -> float:
        # Only the initial stop or, once breakeven has triggered, the entry price is treated as a resting order.
        # The EMA trail is close-confirmed and fills at the next open.
        if ex.mode == "hard":
            return pos.active_stop
        return max(pos.stop, pos.entry_price if pos.breakeven else pos.stop)

    def try_fill(pend: _Pending, s: _Series, k: int, today: date, equity: float, size_mult: float,
                 sector_counts: dict[str, int], sector_values: dict[str, float]) -> str:
        """Returns 'filled', 'wait' (try again next session), or the reason the signal is dropped."""
        o, h = s.open[k], s.high[k]
        if not (o >= pend.entry_ref or h >= pend.entry_ref):
            return "wait"
        if vcp_entry is not None and o > pend.entry_ref * (1.0 + vcp_entry.max_open_above_ref_pct):
            return "skipped_chase"
        fill = max(o, pend.entry_ref)
        stop = pend.stop if vcp_entry is None else max(pend.stop, fill * (1.0 - vcp_entry.max_stop_below_fill_pct))
        budget = equity * sz.risk_per_trade * size_mult * max(0.0, pend.size_mult)
        heat = sum(p.initial_risk * p.shares for p in book.positions)
        if budget <= 0.0 or (heat + budget) / equity > sz.max_heat_pct:
            return "skipped_portfolio"
        net_entry = costs.buy(fill)
        net_risk = net_entry - costs.sell(stop)
        if net_risk <= 0.0:
            return "wait"
        shares = min(budget / net_risk, book.cash / net_entry, sz.max_name_pct * equity / net_entry)
        cost = shares * net_entry
        if shares <= MIN_SHARES:
            return "wait"
        sector = sector_of(pend.symbol)
        if capped(sector):
            if sz.max_sector_positions > 0 and sector_counts.get(sector, 0) >= sz.max_sector_positions:
                return "skipped_sector_positions"
            if sz.max_sector_pct < 1.0 and (sector_values.get(sector, 0.0) + cost) / equity > sz.max_sector_pct:
                return "skipped_sector_pct"
        if cost > book.cash:
            return "wait"
        book.cash -= cost
        book.positions.append(_Position(
            symbol=pend.symbol, signal_date=pend.signal_date, entry_ref=pend.entry_ref, stop=stop,
            entry_date=today, entry_price=fill, shares=shares, active_stop=stop,
            initial_risk=fill - stop, mae_price=fill, mfe_price=fill,
        ))
        sector_values[sector] += cost
        sector_counts[sector] += 1
        return "filled"

    for today in calendar:
        if daily_yield and book.cash > 0.0:
            book.cash += book.cash * daily_yield

        # --- open positions: exits ---
        i = 0
        while i < len(book.positions):
            pos = book.positions[i]
            s = series.get(pos.symbol)
            k = s.index.get(today) if s else None
            if k is None:
                i += 1
                continue
            pos.bars_held += 1
            o, h, lo, c = s.open[k], s.high[k], s.low[k], s.close[k]
            holding_days = (today - pos.entry_date).days

            if pos.pending_exit is not None:
                close_out(pos, today, o, f"{pos.pending_exit}_next_open")
                book.positions.pop(i)
                continue

            stop_now = session_stop(pos)
            if o <= stop_now:
                pos.mae_price = min(pos.mae_price, o)
                pos.mfe_price = max(pos.mfe_price, o)
                close_out(pos, today, o, "stopped")
                book.positions.pop(i)
                continue

            pos.mae_price = min(pos.mae_price, lo)
            pos.mfe_price = max(pos.mfe_price, h)
            if lo <= stop_now:
                close_out(pos, today, stop_now, "intraday_stop")
                book.positions.pop(i)
                continue

            if pos.initial_risk > 0.0:
                peak_r = (pos.mfe_price - pos.entry_price) / pos.initial_risk
                open_r = (c - pos.entry_price) / pos.initial_risk
            else:
                peak_r = open_r = 0.0
            if (pos.bars_held >= ex.stagnation_bars and peak_r < ex.stagnation_max_mfe_r
                    and open_r <= ex.stagnation_max_open_r):
                pos.pending_exit = "stagnation"
                i += 1
                continue

            if not pos.breakeven and c >= pos.entry_price + ex.breakeven_r * pos.initial_risk:
                pos.breakeven = True
                pos.active_stop = max(pos.active_stop, pos.entry_price)
            if pos.breakeven and ex.mode != "hard":
                fast = ex.mode == "ema10"
                if ex.mode == "ema_hybrid" and pos.initial_risk > 0.0:
                    fast = peak_r >= ex.tighten_r
                trail = s.sma[k] if ex.mode == "sma" else s.ema10[k] if fast else s.ema21[k]
                if trail > 0.0:
                    pos.active_stop = max(pos.active_stop, trail)
            if c <= pos.active_stop:
                pos.pending_exit = ("initial_stop" if not pos.breakeven
                                    else "breakeven_stop" if ex.mode == "hard" else f"trail_{ex.mode}")
            elif holding_days >= ex.max_hold_days:
                close_out(pos, today, c, "max_hold")
                book.positions.pop(i)
                continue
            i += 1

        # --- mark to liquidation value; drawdown breaker ---
        invested = 0.0
        sector_counts: dict[str, int] = defaultdict(int)
        sector_values: dict[str, float] = defaultdict(float)
        for p in book.positions:
            s2 = series[p.symbol]
            k2 = s2.index.get(today)
            value = p.shares * (s2.close[k2] if k2 is not None else p.entry_price) * costs.slip_sell * costs.charge_sell
            invested += value
            sector_counts[sector_of(p.symbol)] += 1
            sector_values[sector_of(p.symbol)] += value
        equity = book.cash + invested
        book.peak = max(book.peak, equity)
        dd = (book.peak - equity) / book.peak if book.peak > 0.0 else 0.0
        if dd >= br.close_dd and book.positions:
            for p in list(book.positions):
                s2 = series[p.symbol]
                k2 = s2.index.get(today)
                close_out(p, today, s2.close[k2] if k2 is not None else p.entry_price, "drawdown_close")
            book.positions.clear()
            sector_counts, sector_values = defaultdict(int), defaultdict(float)
            equity = book.cash
            dd = (book.peak - equity) / book.peak if book.peak > 0.0 else 0.0

        for r in by_day.get(today, []):
            book.pending.append(_Pending(r["symbol"], r["signal_date"], r["entry_ref"], r["stop"],
                                         float(r["size_mult"]) if r["size_mult"] is not None else 1.0))

        size_mult = 0.0 if dd >= br.stop_dd else 0.5 if dd >= br.half_dd else 1.0

        # --- pending signals: fills ---
        j = 0
        while j < len(book.pending):
            pend = book.pending[j]
            if today <= pend.signal_date:
                j += 1
                continue
            s = series.get(pend.symbol)
            if s is None:
                outcome = "missing_data"
            else:
                k = s.index.get(today)
                if k is None:
                    j += 1  # a missing bar does not use up a pending session
                    continue
                pend.bars_checked += 1
                if size_mult == 0.0 or len(book.positions) >= sz.max_positions or equity <= 0.0:
                    outcome = "wait"
                else:
                    outcome = try_fill(pend, s, k, today, equity, size_mult, sector_counts, sector_values)
            if outcome == "filled":
                book.pending.pop(j)
            elif outcome == "wait" and pend.bars_checked < en.pending_bars:
                j += 1
            else:
                status = "not_filled" if outcome == "wait" else outcome
                book.skipped.append({"symbol": pend.symbol, "signal_date": pend.signal_date, "status": status})
                book.pending.pop(j)

        # --- end-of-day equity at closing prices ---
        invested = 0.0
        for p in book.positions:
            s2 = series[p.symbol]
            k2 = s2.index.get(today)
            invested += p.shares * (s2.close[k2] if k2 is not None else p.entry_price)
        equity = book.cash + invested
        book.peak = max(book.peak, equity)
        equity_rows.append({"date": today, "equity": equity, "cash": book.cash, "invested_value": invested,
                            "open_positions": len(book.positions), "size_mult": size_mult})

    last = calendar[-1]
    for p in list(book.positions):
        s2 = series[p.symbol]
        k2 = s2.index.get(last)
        close_out(p, last, s2.close[k2] if k2 is not None else p.entry_price, "open")

    trades = pl.from_dicts(book.trades, schema=TRADE_SCHEMA).sort("signal_date", "symbol")
    return SimResult(
        trades=trades,
        equity=pl.from_dicts(equity_rows, schema=EQUITY_SCHEMA),
        skipped=pl.from_dicts(book.skipped, schema=SKIPPED_SCHEMA),
    )
