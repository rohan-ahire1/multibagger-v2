"""M137: offline Dhan order plan and holdings check (docs/research/m137.md)."""
import gzip
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mb.cli import app
from mb.config.loader import load_live_config
from mb.live import broker
from mb.sources import dhan_scrips

REPO = Path(__file__).resolve().parents[1]
CFG = REPO / "configs/live/dhan_m106.yaml"
HEADER = ("SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_EXPIRY_CODE,SEM_TRADING_SYMBOL,"
          "SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE,"
          "SEM_EXPIRY_FLAG,SEM_EXCH_INSTRUMENT_TYPE,SEM_SERIES,SM_SYMBOL_NAME")
ROWS = ["NSE,E,101,EQUITY,0,AAA,1.0,A,,,,5.0000,NA,ES,EQ,A LTD",
        "NSE,E,102,EQUITY,0,BBB,1.0,B,,,,1.0000,NA,ES,EQ,B LTD",
        "NSE,E,999,EQUITY,0,BBB,1.0,B NCD,,,,5.0000,NA,DEB,D1,B NCD",      # other series: ignored
        "BSE,E,555,EQUITY,0,CCC,1.0,C,,,,1.0000,NA,ES,A,C LTD",            # other exchange: ignored
        "NSE,E,103,EQUITY,0,CCC,1.0,C,,,,1.0000,NA,ES,BE,C LTD",
        "NSE,E,14428,EQUITY,0,GOLDBEES,1.0,Gold,,,,1.0000,NA,ETF,EQ,GOLD BEES"]


@pytest.fixture
def cfg():
    return load_live_config(CFG)


@pytest.fixture
def scrips(cfg, tmp_path):
    f = tmp_path / "2026-10-23.csv.gz"
    f.write_bytes(gzip.compress(("\n".join([HEADER, *ROWS]) + "\n").encode()))
    return dhan_scrips.load(cfg.scrips, f)


def _dec(orders, held=None, picks=None, equity=1_000_000.0):
    held = held or {}
    return broker.Decision("2026-10-30", equity, set(picks if picks is not None else
                                                     [o["symbol"] for o in orders if o["side"] == "buy"] + list(held)),
                           held, {s: 100.0 for s in held}, orders)


def _o(sym, side, shares, ref=100.0):
    return {"symbol": sym, "side": side, "shares": shares, "ref_price": ref}


def test_scrip_master_keeps_configured_exchange_segment_and_series(scrips):
    assert sorted(scrips) == ["AAA", "BBB", "CCC", "GOLDBEES"]
    assert scrips["BBB"] == [dhan_scrips.Scrip("102", "EQ", 0.01)]
    assert scrips["AAA"][0].tick == 0.05
    assert scrips["CCC"][0].series == "BE"


def test_payloads_sells_first_scaled_to_live_capital(cfg, scrips, tmp_path):
    dec = _dec([_o("BBB", "buy", 300), _o("AAA", "sell", 200), _o("GOLDBEES", "buy", 1000, 80.0)],
               held={"AAA": 200}, picks=["BBB", "GOLDBEES"], equity=2_000_000.0)
    p = broker.plan(cfg, dec, scrips, tmp_path)
    assert p["factor"] == 0.5
    assert [(o["symbol"], o["side"], o["shares"]) for o in p["orders"]] == [
        ("AAA", "sell", 100), ("BBB", "buy", 150), ("GOLDBEES", "buy", 500)]
    sell, buy = p["orders"][0]["payload"], p["orders"][1]["payload"]
    assert sell == {"correlationId": "20261030-01s", "transactionType": "SELL", "exchangeSegment": "NSE_EQ",
                    "productType": "CNC", "orderType": "MARKET", "validity": "DAY", "securityId": "101",
                    "quantity": 100, "disclosedQuantity": 0, "price": 0.0, "afterMarketOrder": True,
                    "amoTime": "PRE_OPEN"}
    assert buy["amoTime"] == "OPEN" and buy["securityId"] == "102" and buy["transactionType"] == "BUY"
    assert all(len(o["payload"]["correlationId"]) <= 30 for o in p["orders"])
    assert p["buy_value"] == 150 * 100.0 + 500 * 80.0


def test_orders_rounding_to_zero_are_skipped_with_a_note(cfg, scrips, tmp_path):
    p = broker.plan(cfg, _dec([_o("BBB", "buy", 1)], equity=4_000_000.0), scrips, tmp_path)
    assert p["orders"] == [] and "0 shares" in p["notes"][0]


def test_limit_prices_round_to_tick_toward_the_close(cfg, scrips, tmp_path):
    lim = cfg.model_copy(update={"buy": cfg.buy.model_copy(update={"order_type": "LIMIT", "limit_buffer_frac": 0.02}),
                                 "sell": cfg.sell.model_copy(update={"order_type": "LIMIT", "limit_buffer_frac": 0.02})})
    dec = _dec([_o("AAA", "buy", 10, 101.13), _o("CCC", "sell", 5, 50.07)], held={"CCC": 5}, picks=["AAA"])
    p = broker.plan(lim, dec, scrips, tmp_path)
    px = {o["symbol"]: o["payload"]["price"] for o in p["orders"]}
    assert px == {"AAA": 103.15, "CCC": 49.07}   # 103.1526 down to 0.05; 49.0686 up to 0.01


@pytest.mark.parametrize("orders,held,expect", [
    ([_o("ZZZ", "buy", 10)], {}, "ZZZ: 0 scrip-master rows"),
    ([_o("AAA", "buy", 7000)], {}, "above max_order_value_inr"),
    ([_o("AAA", "buy", 1300)], {}, "AAA: weight 0.130 after the plan above 0.120"),
    ([_o("AAA", "sell", 5)], {"AAA": 3}, "AAA: sell 5 but the live book holds 3"),
])
def test_each_rail_refuses_the_plan(cfg, scrips, tmp_path, orders, held, expect):
    with pytest.raises(broker.Refused) as e:
        broker.plan(cfg, _dec(orders, held=held), scrips, tmp_path)
    assert any(expect in r for r in e.value.reasons), e.value.reasons


def test_buy_total_order_count_and_kill_switch(cfg, scrips, tmp_path):
    many = cfg.model_copy(update={"rails": cfg.rails.model_copy(update={"max_orders": 1, "max_buy_frac": 0.1})})
    with pytest.raises(broker.Refused) as e:
        broker.plan(many, _dec([_o("AAA", "buy", 600), _o("BBB", "buy", 600)]), scrips, tmp_path)
    assert any("above max_orders 1" in r for r in e.value.reasons)
    assert any("above max_buy_frac" in r for r in e.value.reasons)
    stop = tmp_path / cfg.rails.kill_switch_file
    stop.parent.mkdir(parents=True)
    stop.write_text("")
    with pytest.raises(broker.Refused) as e:
        broker.plan(cfg, _dec([_o("BBB", "buy", 1)]), scrips, tmp_path)
    assert e.value.reasons == [f"kill switch {cfg.rails.kill_switch_file} is present"]


def test_gold_has_its_own_weight_cap(cfg, scrips, tmp_path):
    p = broker.plan(cfg, _dec([_o("GOLDBEES", "buy", 6000, 100.0)]), scrips, tmp_path)
    assert p["orders"][0]["shares"] == 6000


def test_holdings_set_full_exit_quantity_and_starting_weights(cfg, scrips, tmp_path):
    dec = _dec([_o("AAA", "sell", 200), _o("BBB", "sell", 50)], held={"AAA": 200, "BBB": 400}, picks=["BBB"])
    p = broker.plan(cfg, dec, scrips, tmp_path, holdings={"AAA": 213, "BBB": 400})
    assert [(o["symbol"], o["shares"]) for o in p["orders"]] == [("AAA", 213), ("BBB", 50)]
    assert broker.holdings_qty([{"tradingSymbol": "AAA", "totalQty": 3}, {"tradingSymbol": "BBB", "totalQty": 0},
                                {"tradingSymbol": "AAA", "totalQty": 2}]) == {"AAA": 5}


def test_reconcile(cfg):
    pos = {"AAA": (100, 10.0), "BBB": (50, 20.0)}
    assert broker.reconcile(cfg, pos, {"AAA": 200, "BBB": 100}) == []         # same weights at twice the size
    gaps = broker.reconcile(cfg, pos, {"AAA": 200, "BBB": 50, "CCC": 1})
    assert gaps[0] == "CCC: held at the broker (1), not in the paper book"
    assert gaps[1:] == ["AAA: broker weight 0.667 vs paper 0.500", "BBB: broker weight 0.333 vs paper 0.500"]
    assert broker.reconcile(cfg, pos, {"AAA": 100}) == ["BBB: in the paper book (50), not held at the broker",
                                                       "AAA: broker weight 1.000 vs paper 0.500"]


def test_cli_plan_from_pending_orders_and_reconcile(tmp_path):
    root = tmp_path / "repo"
    for sub in ("configs", "strategies/momentum/configs"):
        shutil.copytree(REPO / sub, root / sub)
    (root / "data/raw/dhan_scrips").mkdir(parents=True)
    (root / "data/raw/dhan_scrips/2026-10-23.csv.gz").write_bytes(gzip.compress(("\n".join([HEADER, *ROWS]) + "\n").encode()))
    paper = root / "data/paper/momentum_b_top25_gold25_jr_gap"
    (paper / "days").mkdir(parents=True)
    orders = [{"symbol": "BBB", "side": "buy", "shares": 100, "ref_price": 50.0}]
    rec = {"session": "2026-10-30", "positions": [], "decision": {"equity_at_close": 1_000_000.0, "picks": ["BBB"],
                                                                  "orders": orders}}
    (paper / "days/2026-10-30.json").write_text(json.dumps(rec))
    book = {"as_of": "2026-10-30", "cash": 1_000_000.0, "positions": {},
            "pending": {"decided": "2026-10-30", "orders": [{"symbol": "BBB", "side": "buy", "shares": 100}]}}
    (paper / "book.json").write_text(json.dumps(book))
    r = CliRunner().invoke(app, ["live", "plan", str(root / "configs/live/dhan_m106.yaml"), "--root", str(root)])
    assert r.exit_code == 0, r.output
    saved = json.loads((root / "data/live/dhan_m106/plans/2026-10-30.json").read_text())
    assert saved["orders"][0]["payload"]["securityId"] == "102" and saved["scrips_file"] == "2026-10-23.csv.gz"
    held = tmp_path / "h.json"
    held.write_text(json.dumps([{"tradingSymbol": "BBB", "totalQty": 100}]))
    r = CliRunner().invoke(app, ["live", "reconcile", str(root / "configs/live/dhan_m106.yaml"), "--holdings", str(held),
                                 "--root", str(root)])
    assert r.exit_code != 0 and "BBB: held at the broker (100), not in the paper book" in r.output
