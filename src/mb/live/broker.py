"""M137: offline Dhan order plan and holdings check (docs/research/m137.md). Nothing here talks to Dhan.

`plan` turns a paper book's decision into Dhan v2 `POST /orders` bodies at the live capital, behind the rails of the
live config; `reconcile` compares a saved Dhan `GET /holdings` response with the paper book.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mb.config.models import LiveConfig, LiveOrderLeg
from mb.sources.dhan_scrips import Scrip

_EPS = 1e-9


class Refused(RuntimeError):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("; ".join(reasons))


@dataclass(frozen=True)
class Decision:
    """What `plan` needs from one paper day record (`days/<decided>.json`)."""
    decided: str
    equity: float                       # paper equity at the decision close
    picks: set[str]
    held: dict[str, int]                # paper shares at the decision close, before the orders
    closes: dict[str, float]            # paper close of each held name at the decision
    orders: list[dict[str, Any]]        # symbol, side, shares, ref_price


def decision_from_day(rec: dict[str, Any]) -> Decision:
    d = rec.get("decision")
    if not d:
        raise Refused([f"{rec['session']}: no decision that day"])
    return Decision(rec["session"], d["equity_at_close"], set(d["picks"]),
                    {p["symbol"]: p["shares"] for p in rec["positions"]},
                    {p["symbol"]: p["close"] for p in rec["positions"]}, d["orders"])


def holdings_qty(holdings: list[dict[str, Any]]) -> dict[str, int]:
    """tradingSymbol -> totalQty from a Dhan GET /holdings response (rows with nothing held dropped)."""
    out: dict[str, int] = {}
    for h in holdings:
        out[h["tradingSymbol"]] = out.get(h["tradingSymbol"], 0) + int(h["totalQty"])
    return {s: q for s, q in out.items() if q != 0}


def _price(leg: LiveOrderLeg, side: str, ref: float, tick: float) -> float:
    if leg.order_type == "MARKET":
        return 0.0
    assert leg.limit_buffer_frac is not None
    if side == "buy":
        px = math.floor(ref * (1.0 + leg.limit_buffer_frac) / tick + _EPS) * tick
    else:
        px = math.ceil(ref * (1.0 - leg.limit_buffer_frac) / tick - _EPS) * tick
    return round(px, 2)


def plan(cfg: LiveConfig, dec: Decision, scrips: dict[str, list[Scrip]], root: Path,
         holdings: dict[str, int] | None = None) -> dict[str, Any]:
    """Orders for the live book (sells first). Raises Refused with every reason when any rail or lookup fails.

    Without `holdings` the live book is assumed to be the paper book scaled to `capital_inr`; with them, a full exit
    sells the broker's quantity and weights after the plan start from the broker's holdings."""
    reasons: list[str] = []
    notes: list[str] = []
    if (root / cfg.rails.kill_switch_file).exists():
        reasons.append(f"kill switch {cfg.rails.kill_switch_file} is present")
    factor = cfg.capital_inr / dec.equity
    live = (dict(holdings) if holdings is not None
            else {s: math.floor(n * factor + _EPS) for s, n in dec.held.items()})
    refs = dict(dec.closes)
    out: list[dict[str, Any]] = []
    for o in sorted(dec.orders, key=lambda o: (o["side"] != "sell", o["symbol"])):
        sym, side, ref = o["symbol"], o["side"], o["ref_price"]
        refs[sym] = ref
        rows = scrips.get(sym, [])
        if len(rows) != 1:
            reasons.append(f"{sym}: {len(rows)} scrip-master rows for the configured series (need exactly 1)")
            continue
        full_exit = side == "sell" and sym not in dec.picks
        qty = live.get(sym, 0) if full_exit and holdings is not None else math.floor(o["shares"] * factor + _EPS)
        if qty <= 0:
            notes.append(f"{sym}: {side} of {o['shares']} paper shares is 0 shares at the live capital; skipped")
            continue
        if side == "sell" and qty > live.get(sym, 0):
            reasons.append(f"{sym}: sell {qty} but the live book holds {live.get(sym, 0)}")
            continue
        value = qty * ref
        if value > cfg.rails.max_order_value_inr:
            reasons.append(f"{sym}: {side} value ₹{value:,.0f} above max_order_value_inr ₹{cfg.rails.max_order_value_inr:,.0f}")
        live[sym] = live.get(sym, 0) + (qty if side == "buy" else -qty)
        leg = cfg.buy if side == "buy" else cfg.sell
        payload = {"correlationId": f"{dec.decided.replace('-', '')}-{len(out) + 1:02d}{side[0]}",
                   "transactionType": side.upper(), "exchangeSegment": cfg.exchange_segment,
                   "productType": cfg.product_type, "orderType": leg.order_type, "validity": cfg.validity,
                   "securityId": rows[0].security_id, "quantity": qty, "disclosedQuantity": 0,
                   "price": _price(leg, side, ref, rows[0].tick), "afterMarketOrder": True, "amoTime": leg.amo_time}
        out.append({"symbol": sym, "series": rows[0].series, "side": side, "shares": qty, "ref_price": ref,
                    "value": value, "payload": payload})
    if len(out) > cfg.rails.max_orders:
        reasons.append(f"{len(out)} orders above max_orders {cfg.rails.max_orders}")
    buys = sum(o["value"] for o in out if o["side"] == "buy")
    if buys > cfg.rails.max_buy_frac * cfg.capital_inr + _EPS:
        reasons.append(f"buys ₹{buys:,.0f} above max_buy_frac x capital ₹{cfg.rails.max_buy_frac * cfg.capital_inr:,.0f}")
    for sym, n in sorted(live.items()):
        if n <= 0 or sym not in refs:
            continue
        w = n * refs[sym] / cfg.capital_inr
        cap = cfg.rails.max_weight_by_symbol.get(sym, cfg.rails.max_name_weight)
        if w > cap + _EPS:
            reasons.append(f"{sym}: weight {w:.3f} after the plan above {cap:.3f}")
    if reasons:
        raise Refused(reasons)
    return {"name": cfg.name, "decided": dec.decided, "capital_inr": cfg.capital_inr, "paper_equity": dec.equity,
            "factor": factor, "orders": out, "buy_value": buys,
            "sell_value": sum(o["value"] for o in out if o["side"] == "sell"), "notes": notes}


def render(p: dict[str, Any], scrips_file: str) -> str:
    lines = [f"# {p['name']}: Dhan order plan for the {p['decided']} decision (not sent)", "",
             f"Live capital ₹{p['capital_inr']:,.0f} = {p['factor']:.4f} x paper equity ₹{p['paper_equity']:,.0f}. "
             f"Sells ₹{p['sell_value']:,.0f}, buys ₹{p['buy_value']:,.0f}. Scrip master `{scrips_file}`.", "",
             "| # | Symbol | Side | Qty | Ref close | ≈ Value (₹) | Type | AMO | Price | Security id |",
             "|---:|---|---|---:|---:|---:|---|---|---:|---|"]
    for i, o in enumerate(p["orders"], 1):
        q = o["payload"]
        lines.append(f"| {i} | {o['symbol']} | {o['side']} | {o['shares']} | {o['ref_price']:,.2f} | {o['value']:,.0f} | "
                     f"{q['orderType']} | {q['amoTime']} | {q['price']:,.2f} | {q['securityId']} |")
    if not p["orders"]:
        lines.append("| | no orders | | | | | | | | |")
    if p["notes"]:
        lines += ["", "Notes:", *[f"- {n}" for n in p["notes"]]]
    return "\n".join(lines) + "\n"


def write(p: dict[str, Any], scrips_file: str, root: Path) -> Path:
    d = root / "data" / "live" / p["name"] / "plans"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{p['decided']}.json").write_text(json.dumps({**p, "scrips_file": scrips_file}, indent=2) + "\n")
    out = d / f"{p['decided']}.md"
    out.write_text(render(p, scrips_file))
    return out


def reconcile(cfg: LiveConfig, positions: dict[str, tuple[int, float]], holdings: dict[str, int]) -> list[str]:
    """Mismatches between the broker's holdings and the paper book (`positions`: symbol -> (shares, last close)).

    Weights are each name's share of the invested value on its side, priced at the paper book's last closes, so the
    live capital and cash do not matter. A name held on one side only is always a mismatch."""
    out = [f"{s}: held at the broker ({holdings[s]}), not in the paper book" for s in sorted(set(holdings) - set(positions))]
    out += [f"{s}: in the paper book ({positions[s][0]}), not held at the broker" for s in sorted(set(positions) - set(holdings))]
    both = sorted(set(holdings) & set(positions))
    paper_total = sum(n * px for n, px in positions.values())
    live_total = sum(holdings[s] * positions[s][1] for s in both)
    if paper_total <= 0 or live_total <= 0:
        return out
    for s in both:
        wp = positions[s][0] * positions[s][1] / paper_total
        wl = holdings[s] * positions[s][1] / live_total
        if abs(wl - wp) > cfg.rails.reconcile_weight_tol:
            out.append(f"{s}: broker weight {wl:.3f} vs paper {wp:.3f}")
    return out
