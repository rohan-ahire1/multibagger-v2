"""M139: short index futures overlay in risk-off (src/mb/strategy/hedged) and the F&O bhavcopy adapter."""
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import polars as pl
import pytest

from mb.config.loader import ConfigError, load_strategy_config
from mb.sources.nse_fo_bhav import SCHEMA, parse_legacy
from mb.strategy.hedged.params import Hedge
from mb.strategy.hedged.run import load_base, overlay

ROOT = Path(__file__).resolve().parents[1]
D = [date(2020, 1, 1) + timedelta(days=i) for i in range(10)]   # ten "sessions"


def hedge(**kw: object) -> Hedge:
    base = dict(signal_symbol="X", sma_sessions=200, ratio=0.5, futures_raw_dir="x", futures_symbol="NIFTY",
                roll_sessions=1, cost_bps_per_side=0.0)
    return Hedge(**{**base, **kw})  # type: ignore[arg-type]


def fut(rows: list[tuple[date, date, float | None, float]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema={"d": pl.Date, "expiry": pl.Date, "o": pl.Float64, "c": pl.Float64}, orient="row")


def flat_base(v: float = 1000.0) -> list[tuple[date, float]]:
    return [(d, v) for d in D]


def test_risk_on_never_trades():
    f = fut([(d, D[-1], 100.0, 100.0 + i) for i, d in enumerate(D)])
    r = overlay(flat_base(), {D[0]: True, D[5]: True}, f, hedge(cost_bps_per_side=5.0))
    assert all(v == 0.0 for v in r.pnl.values()) and r.cost == 0.0 and r.short_sessions == 0


def test_short_opens_next_open_and_closes_next_open():
    # one contract expiring far away; prices: open 100 + i, close 101 + i
    far = date(2021, 1, 1)
    f = fut([(d, far, 100.0 + i, 101.0 + i) for i, d in enumerate(D)])
    r = overlay(flat_base(), {D[0]: False, D[3]: True}, f, hedge(ratio=0.5, cost_bps_per_side=10.0))
    q = 500.0 / 101.0                      # notional 0.5 x 1000 at D1's open (101)
    assert r.pnl[D[0]] == 0.0
    assert r.pnl[D[1]] == pytest.approx(-q * (102.0 - 101.0) - 0.001 * 500.0)
    assert r.pnl[D[2]] == pytest.approx(-q * (103.0 - 102.0))
    assert r.pnl[D[3]] == pytest.approx(-q * (104.0 - 103.0))
    # risk-on at D3's close: closed at D4's open (104), P&L from D3's close (104) to it is 0, cost on q x 104
    assert r.pnl[D[4]] == pytest.approx(-0.001 * q * 104.0)
    assert all(r.pnl[d] == 0.0 for d in D[5:])
    assert r.short_sessions == 3


def test_resize_on_consecutive_risk_off_uses_book_with_hedge_cash():
    far = date(2021, 1, 1)
    f = fut([(d, far, 100.0, 100.0 if i < 2 else 90.0) for i, d in enumerate(D)])
    r = overlay(flat_base(), {D[0]: False, D[2]: False}, f, hedge(ratio=0.5, cost_bps_per_side=0.0))
    q1 = 500.0 / 100.0
    assert r.pnl[D[2]] == pytest.approx(q1 * 10.0)          # price fell 100 -> 90 on D2
    # at D3's open (100) the short is first marked from 90 to 100, then resized to 0.5 x (1000 + 50) at 100
    assert r.pnl[D[3]] == pytest.approx(-q1 * 10.0 + (525.0 / 100.0) * 10.0)


def test_roll_keeps_notional_and_charges_two_legs():
    near, nxt = D[4], date(2021, 1, 1)
    rows = [(d, near, 100.0, 100.0) for d in D[:5]] + [(d, nxt, 200.0, 200.0) for d in D]
    r = overlay(flat_base(), {D[0]: False}, fut(rows), hedge(ratio=0.5, roll_sessions=1, cost_bps_per_side=10.0))
    # D1 open: near has 3 sessions left (> 1), so it is used; at D3's close it has 1 left -> roll into nxt at 200
    assert r.rolls == 1
    assert r.pnl[D[3]] == pytest.approx(-2 * 0.001 * 500.0)
    assert r.cost == pytest.approx(0.001 * 500.0 * 3)


def test_missing_close_carries_the_last_price():
    far = date(2021, 1, 1)
    rows = [(d, far, 100.0, 100.0) for i, d in enumerate(D) if i != 2]
    r = overlay(flat_base(), {D[0]: False}, fut(rows), hedge())
    assert r.stale_prices == 1 and r.pnl[D[2]] == 0.0


def test_no_contract_left_is_an_error():
    rows = [(d, D[1], 100.0, 100.0) for d in D[:2]]
    with pytest.raises(ValueError, match="no NIFTY futures contract"):
        overlay(flat_base(), {D[0]: False}, fut(rows), hedge())


def test_parse_legacy_matches_the_year_file_schema():
    csv = ("INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,"
           "OPEN_INT,CHG_IN_OI,TIMESTAMP,\n"
           "FUTIDX,NIFTY,28-Jan-2021,0,XX,14100,14179.45,13970.05,14165.3,14165.3,134661,1424378.51,12682725,513750,"
           "04-JAN-2021,\n")
    buf = BytesIO()
    with ZipFile(buf, "w") as z:
        z.writestr("fo04JAN2021bhav.csv", csv)
    x = parse_legacy(buf.getvalue())
    assert x.schema == pl.Schema(SCHEMA)
    assert x.row(0, named=True)["expiry"] == date(2021, 1, 28) and x.row(0, named=True)["c"] == 14165.3
    assert x.row(0, named=True)["d"] == date(2021, 1, 4) and x.row(0, named=True)["isin"] is None


def test_candidate_configs_load_and_bases_are_m106_without_the_switch():
    for o in ("", "_off5", "_off10", "_off15"):
        cfg = load_strategy_config(ROOT / f"strategies/hedged/configs/m139_h375{o}.yaml", ROOT)
        base = load_base(cfg, ROOT)
        ref = load_strategy_config(ROOT / f"strategies/momentum/configs/m120_ref{o}.yaml", ROOT)
        b, r = base.params.model_dump(), ref.params.model_dump()
        assert b["regime"].pop("enabled") is False and r["regime"].pop("enabled") is True
        assert b["regime"].pop("risk_off_symbol") is None and r["regime"].pop("risk_off_symbol") == "GOLDBEES"
        assert b == r


def test_base_with_the_switch_on_is_refused(tmp_path):
    ref = ROOT / "strategies/momentum/configs/m120_ref.yaml"
    h = load_strategy_config(ref, ROOT).hash()
    cfg_text = (ROOT / "strategies/hedged/configs/m139_h375.yaml").read_text()
    cfg_text = cfg_text.replace("strategies/momentum/configs/m139_base.yaml", "strategies/momentum/configs/m120_ref.yaml")
    cfg_text = "\n".join(f"    config_hash: {h}" if line.startswith("    config_hash:") else line
                         for line in cfg_text.splitlines())
    p = ROOT / "strategies/hedged/configs" / f"_tmp_{tmp_path.name}.yaml"
    p.write_text(cfg_text)
    try:
        with pytest.raises(ConfigError, match="regime.enabled false"):
            load_base(load_strategy_config(p, ROOT), ROOT)
    finally:
        p.unlink()
