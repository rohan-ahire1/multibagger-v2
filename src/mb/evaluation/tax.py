"""After-tax view of a book (M110): FIFO lots from the fills, Indian capital-gains tax per financial year.

The book's realised gains are split into four buckets: equity or slab-rate fund (gold ETF), short or long term. Each
financial year (April to March) nets them with the set-off rules: a short-term loss can offset any gain, a long-term loss
only long-term gains; whatever is left carries forward (the 8-year limit is ignored). Losses offset the highest-taxed
gains first, as a taxpayer would choose. The yearly equity long-term exemption applies after set-off.

The after-tax book is the pre-tax book scaled by k = after / before; each tax payment scales k down. Tax is paid at the
advance-tax dates on the year's gains so far and settled at the year's end. Approximations: the sale that pays the tax
costs nothing and realises no gain of its own; trades scale linearly with the book (the fixed DP fee does not).
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date

import polars as pl

from mb.config.models import HarvestConfig, MarketConfig, TaxConfig

BUCKETS = ("slab_short", "equity_short", "slab_long", "equity_long")  # highest rate first within each term
EPS_SHARES = 1e-9


@dataclass(frozen=True)
class Lot:
    day: date
    shares: float
    cost_per_share: float  # buy cash flow per share, charges included


def fy_end(d: date) -> int:
    """The calendar year in which d's financial year ends (FY 2025-26 -> 2026)."""
    return d.year + 1 if d.month >= 4 else d.year


def _bucket(symbol: str, held_days: int, cfg: TaxConfig) -> str:
    kind = "slab" if symbol in cfg.slab_symbols else "equity"
    return f"{kind}_{'long' if held_days > cfg.long_term_days else 'short'}"


def realised(fills: pl.DataFrame, cfg: TaxConfig, until: date | None = None) -> tuple[pl.DataFrame, dict[str, deque[Lot]]]:
    """FIFO over the fills (date, symbol, side, shares, cash_flow), up to and including `until`.

    Returns one row per (sale, lot) with date, symbol, bucket, gain; and the lots still open.
    """
    lots: dict[str, deque[Lot]] = defaultdict(deque)
    rows: list[tuple[date, str, str, float]] = []
    f = fills.sort("date", maintain_order=True)
    if until is not None:
        f = f.filter(pl.col("date") <= until)
    for d, s, side, n, flow in f.select("date", "symbol", "side", "shares", "cash_flow").iter_rows():
        if n <= 0.0:
            continue
        if side == "buy":
            lots[s].append(Lot(d, n, -flow / n))
            continue
        per_share, left = flow / n, n
        q = lots[s]
        while left > EPS_SHARES and q:
            lot = q[0]
            take = min(left, lot.shares)
            rows.append((d, s, _bucket(s, (d - lot.day).days, cfg), take * (per_share - lot.cost_per_share)))
            left -= take
            if lot.shares - take > EPS_SHARES:
                q[0] = Lot(lot.day, lot.shares - take, lot.cost_per_share)
            else:
                q.popleft()
        if left > 1e-6 * n:
            raise ValueError(f"{d} {s}: sold {n} shares with only {n - left} in open lots")
    out = pl.DataFrame(rows, schema={"date": pl.Date, "symbol": pl.String, "bucket": pl.String, "gain": pl.Float64},
                       orient="row")
    return out, {s: q for s, q in lots.items() if q}


def unrealised(lots: dict[str, deque[Lot]], prices: dict[str, float], on: date, cfg: TaxConfig) -> dict[str, float]:
    """Gains by bucket if every open lot were sold at `prices` on `on` (no sale costs)."""
    out: dict[str, float] = defaultdict(float)
    for s, q in lots.items():
        for lot in q:
            out[_bucket(s, (on - lot.day).days, cfg)] += lot.shares * (prices[s] - lot.cost_per_share)
    return dict(out)


def year_tax(gains: dict[str, float], carry: tuple[float, float], cfg: TaxConfig) -> tuple[float, tuple[float, float]]:
    """Tax on one financial year's net gains by bucket, given carried (short, long) losses as positive numbers.

    Returns the tax and the losses carried out.
    """
    net = {b: gains.get(b, 0.0) for b in BUCKETS}
    pos = {b: max(v, 0.0) for b, v in net.items()}
    short_loss = carry[0] - sum(min(net[b], 0.0) for b in ("slab_short", "equity_short"))
    long_loss = carry[1] - sum(min(net[b], 0.0) for b in ("slab_long", "equity_long"))
    for b in ("slab_long", "equity_long"):  # long-term losses: long-term gains only
        use = min(long_loss, pos[b])
        pos[b] -= use
        long_loss -= use
    for b in BUCKETS:                         # short-term losses: any gain, highest rate first
        use = min(short_loss, pos[b])
        pos[b] -= use
        short_loss -= use
    pos["equity_long"] = max(pos["equity_long"] - cfg.equity_long_exemption_inr, 0.0)
    rate = {"slab_short": cfg.slab_short_rate, "equity_short": cfg.equity_short_rate,
            "slab_long": cfg.slab_long_rate, "equity_long": cfg.equity_long_rate}
    tax = sum(pos[b] * rate[b] for b in BUCKETS) * (1.0 + cfg.cess)
    return tax, (short_loss, long_loss)


def after_tax(equity: pl.DataFrame, gains: pl.DataFrame, cfg: TaxConfig,
              liquidate: dict[str, float] | None = None) -> pl.DataFrame:
    """equity: date, equity (pre-tax book). gains: date, bucket, gain (pre-tax book, from `realised`). `liquidate`:
    gains by bucket of the lots still open at the last session (from `unrealised`), taxed as if sold then.

    The after-tax book is k x the pre-tax book; a gain realised when the factor is k is k x the pre-tax gain. Tax on the
    year's gains so far is paid up at each advance-tax date and settled at the year's last session (an overpayment,
    after later losses, comes back then) and at the curve's last session.
    Returns date, equity (pre-tax), after (after-tax book), tax (paid that session, negative = refund), k.
    """
    e = equity.select("date", "equity").sort("date")
    days, values = e["date"].to_list(), e["equity"].to_list()
    on_day: dict[date, list[tuple[str, float]]] = defaultdict(list)
    for d, b, g in gains.filter(pl.col("date").is_between(days[0], days[-1])).select("date", "bucket", "gain").iter_rows():
        on_day[d].append((b, g))
    due = [tuple(int(x) for x in md.split("-")) for md in cfg.advance_tax_dates]
    k, carry, ytd, paid_ytd = 1.0, (0.0, 0.0), defaultdict(float), 0.0
    rows = []
    for i, (d, v) in enumerate(zip(days, values)):
        for b, g in on_day.get(d, ()):
            ytd[b] += k * g
        prev = days[i - 1] if i else None
        end_of_year = i + 1 == len(days) or fy_end(days[i + 1]) != fy_end(d)
        instalment = prev is not None and any(prev < date(d.year, m, dd) <= d for m, dd in due)
        pay = 0.0
        if end_of_year:
            year = dict(ytd)
            if i + 1 == len(days):
                for b, g in (liquidate or {}).items():
                    year[b] = year.get(b, 0.0) + k * g
            total, carry_out = year_tax(year, carry, cfg)
            pay = total - paid_ytd
            carry, ytd, paid_ytd = carry_out, defaultdict(float), 0.0
        elif instalment:
            total, _ = year_tax(dict(ytd), carry, cfg)
            pay = max(total - paid_ytd, 0.0)
            paid_ytd += pay
        if pay:
            k = (k * v - pay) / v
        rows.append((d, v, k * v, pay, k))
    return pl.DataFrame(rows, schema={"date": pl.Date, "equity": pl.Float64, "after": pl.Float64, "tax": pl.Float64,
                                      "k": pl.Float64}, orient="row")


def harvest(fills: pl.DataFrame, bars: pl.DataFrame, equity: pl.DataFrame, market: MarketConfig, cfg: TaxConfig,
            h: HarvestConfig) -> tuple[pl.DataFrame, pl.DataFrame]:
    """M113 March tax-loss selling on top of a book's fills (the strategy's own trades are unchanged).

    bars: date, symbol, open, close (the prices the fills use). equity: date, equity (the pre-tax book).
    Each March: sell at the close of session T (h.sell_session_from_month_end back from the month's last) every symbol
    whose open lots, net of sell costs, are at least h.loss_min_frac below cost; with h.harvest_long_term_exemption,
    also long-term equity lots in gain (oldest first) while the year's equity long-term gains stay within the exemption.
    Buy the same shares back at the next session's open. Returns the fills with these trades added, and date, scale:
    the factor on the pre-tax book from each buy-back on (1 - round-trip cost / book), cumulative.
    """
    slip = market.slippage_bps_per_side / 1e4
    buy_f, sell_f = (1 + slip) * (1 + market.buy_charge_rate), (1 - slip) * (1 - market.sell_charge_rate)
    days = equity["date"].to_list()
    value = dict(equity.select("date", "equity").iter_rows())
    close = {(d, s): c for d, s, c in bars.select("date", "symbol", "close").iter_rows() if c is not None}
    opn = {(d, s): o for d, s, o in bars.select("date", "symbol", "open").iter_rows() if o is not None}
    last_close: dict[str, float] = {}
    by_day: dict[date, list[tuple[str, float]]] = defaultdict(list)
    for d, s, c in bars.filter(pl.col("date") <= days[-1]).sort("date").select("date", "symbol", "close").iter_rows():
        if c is not None:
            by_day[d].append((s, c))
    extra: list[tuple] = []
    scale, rows = 1.0, []
    march = defaultdict(list)
    for d in days:
        if d.month == 3:
            march[d.year].append(d)
    pairs = {}
    for ds in march.values():
        if len(ds) >= h.sell_session_from_month_end:
            t = ds[-h.sell_session_from_month_end]
            pairs[t] = ds[ds.index(t) + 1]
    pending: dict[date, float] = {}
    for d in days:
        for s, c in by_day.get(d, ()):
            last_close[s] = c
        if d in pending:
            scale *= 1.0 - pending.pop(d) / value[d]
        rows.append((d, scale))
        if d not in pairs:
            continue
        t1 = pairs[d]
        cur = pl.concat([fills.select(list(FILL_COLUMNS)), _fills(extra)]) if extra else fills.select(list(FILL_COLUMNS))
        gains, lots = realised(cur, cfg, until=d)
        sell: dict[str, float] = {}
        for s, q in lots.items():
            px = last_close.get(s)
            if px is None or (t1, s) not in opn:
                continue
            n = sum(lot.shares for lot in q)
            if n <= EPS_SHARES:  # float dust left by resizing
                continue
            basis = sum(lot.shares * lot.cost_per_share for lot in q)
            if n * px * sell_f <= basis * (1.0 - h.loss_min_frac):
                sell[s] = n
        if h.harvest_long_term_exemption:
            fy = gains.filter(pl.col("date").map_elements(fy_end, return_dtype=pl.Int64) == fy_end(d))
            room = cfg.equity_long_exemption_inr - max(fy.filter(pl.col("bucket") == "equity_long")["gain"].sum(), 0.0)
            for s, q in lots.items():
                px = last_close.get(s)
                if s in sell or s in cfg.slab_symbols or px is None or (t1, s) not in opn:
                    continue
                n = 0.0
                for lot in q:  # FIFO: only a prefix of the queue can be sold
                    g = lot.shares * (px * sell_f - lot.cost_per_share)
                    if (d - lot.day).days <= cfg.long_term_days or g <= 0.0 or g > room:
                        break
                    room -= g
                    n += lot.shares
                if n > EPS_SHARES:
                    sell[s] = n
        cost = 0.0
        for s, n in sell.items():
            px, o = last_close[s], opn[(t1, s)]
            got, paid = n * px * sell_f - market.dp_fee_per_sale_inr, n * o * buy_f
            extra += [(d, s, "sell", n, px, got), (t1, s, "buy", n, o, -paid)]
            cost += paid - got
        if sell:
            pending[t1] = cost
    out = pl.concat([fills.select(list(FILL_COLUMNS)), _fills(extra)]) if extra else fills.select(list(FILL_COLUMNS))
    return out, pl.DataFrame(rows, schema={"date": pl.Date, "scale": pl.Float64}, orient="row")


FILL_COLUMNS = {"date": pl.Date, "symbol": pl.String, "side": pl.String, "shares": pl.Float64, "price": pl.Float64,
                "cash_flow": pl.Float64}


def _fills(rows: list[tuple]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=FILL_COLUMNS, orient="row")
