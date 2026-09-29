"""Paper book for the month-end momentum strategy: whole shares, raw prices, the backtest's costs.

Each session after the book's last one is processed in order:
1. corporate actions on names held overnight: share events from the dataset's matches change the share count, and the
   rest of that session's adjustment step (a dividend, or a rights issue or demerger) is credited as cash, which is
   what the adjusted series the backtest trades on assumes;
2. pending orders fill at the open, sells first, then buys, all buys scaled down together if cash is short;
3. positions are marked at the close;
4. at a month-end close the strategy's target becomes whole-share orders for the next open, sized off that close.

A session with a problem (an unexplained price jump on a held or picked name) is not committed: the book stays at the
session before it, and the next run retries once the data is fixed.

On a dataset built with `link_renames_by_isin` (M14), a renamed stock's bars all carry its later symbol, so a position
and pending orders under the old symbol move to the later one first (step 0).
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from mb.config.loader import Resolved
from mb.config.models import PaperConfig
from mb.data import datasets
from mb.live import calendar
from mb.strategy.momentum.params import Params, ParamsM8, ParamsM10, ParamsM11, ParamsM12, ParamsM19, ParamsM21, ParamsM22
from mb.strategy.momentum.targets import targets

PANEL_COLUMNS = ("date", "symbol", "security_id", "series", "open", "close", "turnover", "adj_open", "adj_close",
                 "adj_factor")
APPLIED_MATCHES = ("matched", "applied_small")
_EPS = 1e-9


class Blocked(RuntimeError):
    def __init__(self, session: date, reasons: list[str]):
        self.session, self.reasons = session, reasons
        super().__init__(f"{session}: " + "; ".join(reasons))


@dataclass
class Position:
    shares: int
    entry: date
    paid: float        # cash paid for all buys, costs included
    received: float    # cash from trims, dividends and fractional entitlements
    last_close: float
    last_date: date


@dataclass
class Book:
    as_of: date | None
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    pending: dict[str, Any] | None = None  # {"decided": iso date, "orders": [{"symbol", "side", "shares"}]}

    def equity(self) -> float:
        return self.cash + sum(p.shares * p.last_close for p in self.positions.values())

    def to_json(self) -> dict[str, Any]:
        return {"as_of": self.as_of.isoformat() if self.as_of else None, "cash": self.cash, "pending": self.pending,
                "positions": {s: {**asdict(p), "entry": p.entry.isoformat(), "last_date": p.last_date.isoformat()}
                              for s, p in sorted(self.positions.items())}}

    @staticmethod
    def from_json(d: dict[str, Any]) -> Book:
        pos = {s: Position(v["shares"], date.fromisoformat(v["entry"]), v["paid"], v["received"], v["last_close"],
                           date.fromisoformat(v["last_date"])) for s, v in d["positions"].items()}
        return Book(date.fromisoformat(d["as_of"]) if d["as_of"] else None, d["cash"], pos, d["pending"])


@dataclass(frozen=True)
class DataView:
    """What the book reads from one dataset version."""
    ref: str
    panel_sha256: str
    panel: pl.DataFrame                     # PANEL_COLUMNS
    share_mult: dict[tuple[date, str], float]  # (session, symbol) -> price multiplier of applied share-count events
    jumps: pl.DataFrame                     # symbol, date, ratio
    # old symbol -> [(first session of the later symbol, final symbol)]: the old symbol's rows before that session
    # carry the final symbol. Empty unless the dataset links renames.
    renames: dict[str, list[tuple[date, str]]] = field(default_factory=dict)

    def renamed(self, sym: str, as_of: date) -> str:
        """The symbol that `sym`, as it was known on `as_of`, carries in this dataset."""
        return next((to for before, to in self.renames.get(sym, []) if as_of < before), sym)


def check_supported(p: Params) -> None:
    """The book trades a plain month-end rebalance. M8 options that need more than that are refused, not ignored."""
    if not isinstance(p, ParamsM8):
        return
    on = [k for k, v in (("ranking.second_lookback_sessions", p.ranking.second_lookback_sessions),
                         ("portfolio.max_per_sector", p.portfolio.max_per_sector),
                         ("sizing.vol_target_annual", p.sizing.vol_target_annual)) if v is not None]
    if not p.portfolio.resize_held:
        on.append("portfolio.resize_held: false")
    if isinstance(p, ParamsM10):  # they read more history than `history_rows` loads
        on += [k for k, v in (("ranking.high_window_sessions", p.ranking.high_window_sessions),
                              ("ranking.residual_beta_sessions", p.ranking.residual_beta_sessions),
                              ("ranking.frog_candidates_per_slot", p.ranking.frog_candidates_per_slot)) if v is not None]
    if isinstance(p, ParamsM11):
        if p.schedule.decision_offset_sessions:
            on.append("schedule.decision_offset_sessions")
        if p.exits.stop_loss_frac is not None:
            on.append("exits.stop_loss_frac")
    if isinstance(p, ParamsM12):
        on += [k for k, v in (("ranking.max_filter_frac", p.ranking.max_filter_frac),
                              ("portfolio.min_momentum", p.portfolio.min_momentum)) if v is not None]
    if isinstance(p, ParamsM21) and p.exits.book_stop_frac is not None:
        on.append("exits.book_stop_frac")
    if isinstance(p, ParamsM22) and p.portfolio.fixed_trend_sessions is not None:
        on.append("portfolio.fixed_trend_sessions")
    if on:
        raise ValueError(f"paper trading does not support these M8/M10/M11/M12/M21/M22 options yet: {', '.join(on)}")


def history_rows(p: Params) -> int:
    """Rows per symbol the strategy reads before a date: every window is a per-symbol shift or rolling over rows."""
    inv = p.portfolio.inverse_vol_sessions if isinstance(p, ParamsM11) and p.portfolio.weighting == "inverse_vol" else 0
    return max(p.ranking.lookback_sessions, p.universe.adv_window_sessions, p.regime.sma_sessions if p.regime.enabled else 0, inv)


def load_view(root: Path, ref: str, start: date, p: Params) -> DataView:
    """Rows from `start` on, plus each symbol's last `history_rows` rows before it (targets are then unchanged)."""
    path = datasets.dataset_path(root, ref)
    manifest = datasets.read_manifest(path)
    scan = pl.scan_parquet(path / datasets.PANEL_FILE).select(PANEL_COLUMNS)
    before = scan.filter(pl.col("date") < start).sort("symbol", "date").group_by("symbol", maintain_order=True).tail(history_rows(p)).select(PANEL_COLUMNS)
    panel = pl.concat([before, scan.filter(pl.col("date") >= start)]).sort("symbol", "date").collect()
    # Price-only actions (rights, demergers) do not change the share count; their step is paid out as cash.
    m = pl.read_parquet(path / "ca_matches.parquet").filter(pl.col("status").is_in(APPLIED_MATCHES) & pl.col("adjusts_volume"))
    mult: dict[tuple[date, str], float] = {}
    for d, s, e in m.select("effective_date", "symbol", "expected").iter_rows():
        mult[(d, s)] = mult.get((d, s), 1.0) * e
    renames: dict[str, list[tuple[date, str]]] = {}
    if (path / "rename_links.parquet").exists():
        for old, before, final in pl.read_parquet(path / "rename_links.parquet").sort("before").select("old", "before", "final").iter_rows():
            renames.setdefault(old, []).append((before, final))
    return DataView(ref, manifest["outputs"][datasets.PANEL_FILE]["sha256"], panel, mult,
                    pl.read_parquet(path / "unexplained_jumps.parquet"), renames)


# --- store ----------------------------------------------------------------------------------------------------------

class Store:
    """`data/paper/<name>/`: book.json, days/<session>.json, tickets/<decided>.md, replays/, daily/."""

    def __init__(self, root: Path, name: str):
        self.dir = root / "data" / "paper" / name

    def load_book(self, cfg: PaperConfig) -> Book:
        f = self.dir / "book.json"
        if not f.exists():
            return Book(None, cfg.initial_capital)
        return Book.from_json(json.loads(f.read_text()))

    def save_book(self, book: Book) -> None:
        write_json(self.dir / "book.json", book.to_json())

    def save_day(self, rec: dict[str, Any]) -> None:
        write_json(self.dir / "days" / f"{rec['session']}.json", rec)

    def days(self) -> list[dict[str, Any]]:
        return [json.loads(p.read_text()) for p in sorted((self.dir / "days").glob("*.json"))]

    def save_text(self, sub: str, name: str, text: str) -> Path:
        out = self.dir / sub / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        return out


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")
    tmp.rename(path)


# --- one session ----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Costs:
    slip: float
    buy_charge: float
    sell_charge: float
    dp_fee: float

    @staticmethod
    def of(strat: Resolved) -> Costs:
        m = strat.market
        return Costs(m.slippage_bps_per_side / 1e4, m.buy_charge_rate, m.sell_charge_rate, m.dp_fee_per_sale_inr)

    def buy(self, value: float) -> float:
        return value * (1 + self.slip) * (1 + self.buy_charge)

    def sell(self, value: float) -> float:
        return value * (1 - self.slip) * (1 - self.sell_charge)


def _session_bars(view: DataView, sessions: list[date]) -> dict[date, dict[str, tuple[float, float, float, float | None,
                                                                                         float | None]]]:
    """session -> symbol -> (open, close, adj_factor, previous close, previous adj_factor)."""
    lo = min(sessions)
    f = (view.panel.select("date", "symbol", "open", "close", "adj_factor").sort("symbol", "date")
         .with_columns(pl.col("close").shift(1).over("symbol").alias("pc"),
                       pl.col("adj_factor").shift(1).over("symbol").alias("pf"))
         .filter(pl.col("date") >= lo))
    out: dict[date, dict[str, tuple]] = {d: {} for d in sessions}
    for d, s, o, c, fa, pc, pf in f.iter_rows():
        if d in out:
            out[d][s] = (o, c, fa, pc, pf)
    return out


def _renames(book: Book, view: DataView, notes: list[str]) -> list[dict]:
    """Moves positions bought, and orders decided, under a symbol that this dataset has relabelled."""
    done: list[dict] = []
    for sym in sorted(book.positions):
        to = view.renamed(sym, book.positions[sym].entry)
        if to == sym:
            continue
        pos = book.positions.pop(sym)
        if to in book.positions:  # cannot happen for a clean link; kept whole rather than dropped
            have = book.positions[to]
            have.shares += pos.shares
            have.paid += pos.paid
            have.received += pos.received
            have.entry = min(have.entry, pos.entry)
            notes.append(f"{sym} -> {to}: merged into an existing position")
        else:
            book.positions[to] = pos
        done.append({"symbol": to, "kind": "rename", "from": sym, "shares": pos.shares})
    if book.pending:
        decided = date.fromisoformat(book.pending["decided"])
        for o in book.pending["orders"]:
            to = view.renamed(o["symbol"], decided)
            if to != o["symbol"]:
                done.append({"symbol": to, "kind": "rename_order", "from": o["symbol"], "side": o["side"]})
                o["symbol"] = to
    return done


def _corporate_actions(book: Book, s: date, bars: dict[str, tuple], view: DataView, notes: list[str]) -> list[dict]:
    done: list[dict] = []
    for sym, pos in book.positions.items():
        bar = bars.get(sym)
        if bar is None or bar[3] is None or bar[4] is None:
            continue
        _, _, fa, pc, pf = bar
        step = pf / fa  # every adjustment effective this session, as a price multiplier
        e = view.share_mult.get((s, sym), 1.0)
        if not math.isclose(e, 1.0):
            before = pos.shares
            exact = before / e
            pos.shares = math.floor(exact + _EPS)
            frac_cash = (exact - pos.shares) * pc * e
            book.cash += frac_cash
            pos.received += frac_cash
            if book.pending:
                for o in book.pending["orders"]:
                    if o["symbol"] == sym:
                        o["shares"] = math.floor(o["shares"] / e + _EPS)
            done.append({"symbol": sym, "kind": "share_event", "price_multiplier": e, "shares_before": before,
                         "shares_after": pos.shares, "fraction_cash": frac_cash})
        d = step / e
        if d < 1 - 1e-7:
            cash = pos.shares * e * (1 - d) * pc  # per pre-event share, on the shares held into the ex-date
            book.cash += cash
            pos.received += cash
            done.append({"symbol": sym, "kind": "cash_adjustment", "per_share": (1 - d) * pc, "cash": cash})
        elif d > 1 + 1e-7:
            notes.append(f"{sym}: adjustment step {step:.6f} on {s} is not explained by its share events ({e:.6f})")
    return done


def _fill(book: Book, s: date, bars: dict[str, tuple], costs: Costs, notes: list[str]) -> tuple[list[dict], list[dict]]:
    fills: list[dict] = []
    closed: list[dict] = []
    orders = book.pending["orders"] if book.pending else []
    for o in (o for o in orders if o["side"] == "sell"):
        pos = book.positions.get(o["symbol"])
        if pos is None:
            continue
        n = min(o["shares"], pos.shares)
        bar = bars.get(o["symbol"])
        if bar is None or not bar[0]:
            px = bar[1] if bar else pos.last_close
            notes.append(f"{o['symbol']}: no open on {s}; sold at the last close {px} as the backtest does")
        else:
            px = bar[0]
        full = n == pos.shares
        flow = costs.sell(n * px) - (costs.dp_fee if full else 0.0)
        book.cash += flow
        pos.shares -= n
        pos.received += flow
        fills.append({"symbol": o["symbol"], "side": "sell", "shares": n, "price": px, "cash_flow": flow})
        if full:
            closed.append({"symbol": o["symbol"], "entry": pos.entry.isoformat(), "exit": s.isoformat(),
                           "paid": pos.paid, "received": pos.received, "pnl": pos.received - pos.paid})
            del book.positions[o["symbol"]]
    buys = []
    for o in (o for o in orders if o["side"] == "buy"):
        bar = bars.get(o["symbol"])
        if bar is None or not bar[0]:
            notes.append(f"{o['symbol']}: no open on {s}; not bought")
            continue
        buys.append((o["symbol"], o["shares"], bar[0]))
    need = sum(costs.buy(n * px) for _, n, px in buys)
    scale = min(1.0, book.cash / need) if need > 0 else 1.0
    for sym, n, px in buys:
        n = math.floor(n * scale + _EPS) if scale < 1.0 else n
        if n <= 0:
            continue
        cost = costs.buy(n * px)
        if cost > book.cash:  # rounding can leave a rupee short; drop one share
            n -= 1
            cost = costs.buy(n * px)
            if n <= 0:
                continue
        book.cash -= cost
        pos = book.positions.get(sym)
        if pos is None:
            book.positions[sym] = Position(n, s, cost, 0.0, px, s)
        else:
            pos.shares += n
            pos.paid += cost
        fills.append({"symbol": sym, "side": "buy", "shares": n, "price": px, "cash_flow": -cost})
    if scale < 1.0:
        notes.append(f"buys scaled by {scale:.4f}: cash short at the open")
    book.pending = None
    return fills, closed


def _orders(book: Book, s: date, picks: dict[str, float], gross: float, bars: dict[str, tuple], costs: Costs,
            last: dict[str, float] | None = None) -> list[dict]:
    """Whole-share orders that move the book to the target, sized off this close. Integer rounding leaves a small band
    where a held name is not traded: it is sold down only above floor(goal / close) shares and bought up only below
    floor(goal / cost-loaded close). A fixed-weight symbol (M19) that did not trade this session is sized off its last
    close (`last`); ranked picks always have a bar."""
    equity = book.equity()
    total = sum(picks.values())
    out: list[dict] = []
    for sym in sorted(set(book.positions) - set(picks)):
        out.append({"symbol": sym, "side": "sell", "shares": book.positions[sym].shares, "ref_price": book.positions[sym].last_close})
    for sym in sorted(picks):
        ref = bars[sym][1] if sym in bars else (last or {})[sym]
        goal = equity * gross * picks[sym] / total if total > 0 else 0.0
        held = book.positions[sym].shares if sym in book.positions else 0
        hi, lo = math.floor(goal / ref), math.floor(goal / costs.buy(ref))
        if held > hi:
            out.append({"symbol": sym, "side": "sell", "shares": held - hi, "ref_price": ref})
        elif held < lo:
            out.append({"symbol": sym, "side": "buy", "shares": lo - held, "ref_price": ref})
    return out


def _decide(cut: pl.DataFrame, p: Params, start: date, s: date) -> tuple[dict[str, float], float]:
    t = targets(cut, p, start, s)[s]
    return t.weights, t.gross


def _jump_blocks(view: DataView, names: set[str], lo: date, hi: date) -> list[str]:
    hits = view.jumps.filter(pl.col("symbol").is_in(sorted(names)) & pl.col("date").is_between(lo, hi))
    return [f"{sym}: unexplained jump x{r:.3f} on {d}" for sym, d, r in hits.select("symbol", "date", "ratio").iter_rows()]


def advance(book: Book, cfg: PaperConfig, strat: Resolved, view: DataView, holidays: set[date],
            store: Store | None = None) -> tuple[Book, list[dict[str, Any]], list[str]]:
    """Process every session after `book.as_of`. Returns the book, the committed day records and notes.

    Raises Blocked for the first session that cannot be committed; sessions before it are already committed to `store`.
    """
    p = strat.params
    assert isinstance(p, Params)
    check_supported(p)
    costs = Costs.of(strat)
    all_days = sorted(view.panel["date"].unique().to_list())
    todo = [d for d in all_days if d >= cfg.start and (book.as_of is None or d > book.as_of)]
    if not todo:
        return book, [], []
    bars_by_day = _session_bars(view, todo)
    nxt = {d: n for d, n in zip(all_days, all_days[1:])}
    records: list[dict[str, Any]] = []
    all_notes: list[str] = []
    for s in todo:
        work = Book.from_json(json.loads(json.dumps(book.to_json())))  # a session commits whole or not at all
        notes: list[str] = []
        bars = bars_by_day[s]
        ca = _renames(work, view, notes) + _corporate_actions(work, s, bars, view, notes)
        fills, closed = _fill(work, s, bars, costs, notes)
        for sym, pos in work.positions.items():
            if sym in bars:
                pos.last_close, pos.last_date = bars[sym][1], s
            else:
                notes.append(f"{sym}: held, no trade on {s} (last close {pos.last_date})")
        blocks = _jump_blocks(view, set(work.positions), s, s)

        by_cal = calendar.is_month_end(s, holidays)
        by_data = nxt[s].month != s.month if s in nxt else None
        if by_data is not None and by_data != by_cal:
            notes.append(f"{s}: the calendar says month-end={by_cal} but the data says {by_data}; following the data")
        month_end = by_cal if by_data is None else by_data

        decision = None
        if month_end and not blocks:
            cut = view.panel.filter(pl.col("date") <= s)
            picks, gross = _decide(cut, p, cfg.start, s)
            i = all_days.index(s)
            lo = all_days[max(0, i - p.ranking.lookback_sessions)]
            blocks += _jump_blocks(view, set(picks), lo, s)
            if not blocks:
                last = {k: v for k, v in cut.filter(pl.col("symbol").is_in(sorted(set(picks) - set(bars))))
                        .sort("date").group_by("symbol").agg(pl.col("close").last()).iter_rows()}
                orders = _orders(work, s, picks, gross, bars, costs, last)
                work.pending = {"decided": s.isoformat(), "orders": [{k: o[k] for k in ("symbol", "side", "shares")}
                                                                     for o in orders]}
                decision = {"picks": sorted(picks), "gross": gross, "equity_at_close": work.equity(), "orders": orders}
                fixed = isinstance(p, ParamsM19) and bool(p.portfolio.fixed_weights)
                if isinstance(p, ParamsM11) and (p.portfolio.weighting != "equal" or fixed):  # equal-weight records keep their shape
                    total = sum(picks.values())
                    decision["weights"] = {k: picks[k] / total for k in sorted(picks)}
        if blocks:
            raise Blocked(s, blocks)

        work.as_of = s
        rec = {"session": s.isoformat(), "dataset": view.ref, "panel_sha256": view.panel_sha256,
               "strategy_config_hash": strat.hash(), "month_end": month_end, "corporate_actions": ca, "fills": fills,
               "closed": closed, "cash": work.cash, "equity": work.equity(),
               "positions": [{"symbol": sym, "shares": pos.shares, "close": pos.last_close,
                              "value": pos.shares * pos.last_close} for sym, pos in sorted(work.positions.items())],
               "decision": decision, "notes": notes}
        if store is not None:
            store.save_day(rec)
            if decision is not None:
                store.save_text("tickets", f"{s}.md", ticket(cfg, rec))
            store.save_book(work)
        book = work
        records.append(rec)
        all_notes += notes
    return book, records, all_notes


def ticket(cfg: PaperConfig, rec: dict[str, Any]) -> str:
    d = rec["decision"]
    lines = [f"# {cfg.name}: orders decided at the {rec['session']} close", "",
             f"Fill at the next session's open. Equity at the close: ₹{d['equity_at_close']:,.0f}; "
             f"{len(d['picks'])} picks, gross {d['gross']:.2f}. Dataset `{rec['dataset']}`.", "",
             "| Symbol | Side | Shares | Ref close | ≈ Value (₹) |", "|---|---|---:|---:|---:|"]
    for o in d["orders"]:
        lines.append(f"| {o['symbol']} | {o['side']} | {o['shares']} | {o['ref_price']:,.2f} | "
                     f"{o['shares'] * o['ref_price']:,.0f} |")
    if not d["orders"]:
        lines.append("| — | no trades | | | |")
    return "\n".join(lines) + "\n"
