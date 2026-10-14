"""M119: option signals from the F&O bhavcopy (src/mb/data/fno.py) and the options book (src/mb/strategy/options_book)."""
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from pydantic import ValidationError

from mb.config.loader import load_strategy_config
from mb.data import fno
from mb.strategy.options_book.params import Params, Portfolio
from mb.strategy.options_book.run import targets

ROOT = Path(__file__).resolve().parents[1]
D = date(2020, 3, 2)


def test_implied_vol_recovers_the_vol_and_rejects_bad_prices():
    fwd, k, yrs = np.array([100.0, 100.0, 100.0, 100.0]), np.array([90.0, 100.0, 110.0, 95.0]), np.full(4, 30 / 365)
    call = np.array([True, False, True, False])
    vol = np.array([0.2, 0.35, 0.5, 0.8])
    px = fno.black76(fwd, k, yrs, 0.065, vol, call)
    assert np.allclose(fno.implied_vol(px, fwd, k, yrs, 0.065, call), vol, atol=1e-6)
    disc = np.exp(-0.065 * 30 / 365)
    below = np.array([disc * 10.0 - 0.01, 0.0001, 0.0, 200.0])  # under intrinsic, tiny, zero, above the forward
    assert np.isnan(fno.implied_vol(below, fwd, k, yrs, 0.065, call)[[0, 2, 3]]).all()


def bhav(tmp_path, rows):
    cols = ["d", "instrument", "sym", "expiry", "strike", "opt", "c", "vol", "oi", "val_lakh"]
    pl.DataFrame(rows, schema=cols, orient="row").write_parquet(tmp_path / "a.parquet")


def test_chains_keep_traded_rows_and_read_american_labels(tmp_path):
    e = D + timedelta(days=30)
    bhav(tmp_path, [(D, "FUTSTK", "X", e, 0.0, None, 100.0, 5.0, 1.0, 1.0),
                    (D, "OPTSTK", "X", e, 100.0, "CA", 4.0, 1.0, 1.0, 1.0),
                    (D, "OPTSTK", "X", e, 100.0, "PA", 4.0, 1.0, 1.0, 1.0),
                    (D, "OPTSTK", "X", e, 105.0, "CE", 2.0, 0.0, 1.0, 1.0),     # untraded
                    (D, "OPTIDX", "NIFTY", e, 100.0, "CE", 2.0, 9.0, 1.0, 1.0)])
    ch = fno.chains(tmp_path, [D])
    assert ch.select("kind", "strike").rows() == [("CE", 100.0), ("FUT", 0.0), ("PE", 100.0)]


def test_with_iv_uses_the_nearest_expiry_far_enough_away_with_a_traded_future(tmp_path):
    near, mid, far = D + timedelta(days=5), D + timedelta(days=30), D + timedelta(days=60)
    bhav(tmp_path, [(D, "FUTSTK", "X", near, 0.0, None, 100.0, 5.0, 1.0, 1.0),
                    (D, "FUTSTK", "X", far, 0.0, None, 102.0, 5.0, 1.0, 1.0),
                    (D, "OPTSTK", "X", near, 100.0, "CE", 2.0, 1.0, 1.0, 1.0),
                    (D, "OPTSTK", "X", mid, 100.0, "CE", 4.0, 1.0, 1.0, 1.0),  # no traded future at this expiry
                    (D, "OPTSTK", "X", far, 100.0, "CE", 6.0, 1.0, 1.0, 1.0)])
    o = fno.with_iv(fno.chains(tmp_path, [D]), 0.065, 10)
    assert o.select("expiry", "fwd").rows() == [(far, 102.0)] and o["m"][0] == pytest.approx(100 / 102)


def test_call_put_spread_weights_pairs_by_open_interest():
    def row(k, kind, iv, oi, m):
        return (D, "X", kind, k, iv, oi, m)
    o = pl.DataFrame([row(100.0, "CE", 0.30, 10.0, 1.0), row(100.0, "PE", 0.28, 30.0, 1.0),   # +0.02, weight 20
                      row(105.0, "CE", 0.25, 5.0, 1.05), row(105.0, "PE", 0.30, 15.0, 1.05),  # -0.05, weight 10
                      row(120.0, "CE", 0.9, 1e6, 1.2), row(120.0, "PE", 0.1, 1e6, 1.2),       # outside the band
                      row(95.0, "CE", 0.5, 1e6, 0.95)],                                     # no put
                     schema=["d", "sym", "kind", "strike", "iv", "oi", "m"], orient="row")
    got = fno.call_put_spread(o, 0.9, 1.1)
    assert got["value"][0] == pytest.approx((0.02 * 20 - 0.05 * 10) / 30)


def test_skew_takes_the_put_and_call_nearest_their_targets():
    o = pl.DataFrame([(D, "X", "PE", 0.95, 0.40), (D, "X", "PE", 0.93, 0.45), (D, "X", "PE", 0.85, 0.50),
                      (D, "X", "CE", 1.02, 0.30), (D, "X", "CE", 0.99, 0.25), (D, "X", "CE", 1.10, 0.10),
                      (D, "Y", "PE", 0.90, 0.40)],  # Y has no ATM call
                     schema=["d", "sym", "kind", "m", "iv"], orient="row").with_columns(strike=pl.col("m") * 100)
    got = fno.skew(o, 0.80, 0.95, 0.95, 0.95, 1.05, 1.0)
    assert got.rows() == [(D, "X", pytest.approx(0.45 - 0.25))]


def test_window_sum_and_rename_mapping():
    cal = [D + timedelta(days=i) for i in range(5)]
    x = pl.DataFrame({"d": cal, "sym": ["A"] * 5, "shares": [1.0, 2.0, 3.0, 4.0, 5.0]})
    assert fno.window_sum(x, "sym", "shares", cal, 2, [cal[2], cal[4]]).rows() == [(cal[2], "A", 5.0), (cal[4], "A", 9.0)]
    with pytest.raises(ValueError, match="fewer than"):
        fno.window_sum(x, "sym", "shares", cal, 4, [cal[1]])
    links = pl.DataFrame({"old": ["A", "A"], "before": [cal[1], cal[3]], "final": ["B", "C"]})
    got = fno.panel_symbols(x.select("d", "sym"), links)["sym"].to_list()
    assert got == ["B", "C", "C", "A", "A"]


def params(signal, frac):
    cfg = load_strategy_config(ROOT / "strategies/options_book/configs/m119_combo.yaml", ROOT)
    p = cfg.params
    assert isinstance(p, Params)
    return p.model_copy(update={"portfolio": Portfolio(signal=signal, top_frac=frac)})


def test_targets_follow_the_papers_directions_and_round_up():
    t = pl.DataFrame({"date": [D] * 5, "symbol": list("ABCDE"), "call_put_spread": [0.05, 0.01, -0.02, 0.03, 0.0],
                      "skew": [0.10, 0.02, 0.05, 0.01, 0.03], "option_volume": [0.5, 0.1, 0.3, 0.2, 0.4]})
    pick = lambda s, f: sorted(targets(t, params(s, f), [D])[D].weights)  # noqa: E731
    assert pick("call_put_spread", 0.2) == ["A"]
    assert pick("skew", 0.3) == ["B", "D"]               # ceil(1.5) = 2, lowest skew
    assert pick("option_volume", 0.2) == ["B"]
    assert pick("none", 1.0) == list("ABCDE")
    # combo: D ranks 2nd/1st/2nd best -> highest mean percentile
    assert pick("combo", 0.2) == ["D"]
    assert set(targets(t, params("none", 1.0), [D])[D].weights.values()) == {1.0}
    with pytest.raises(ValueError, match="no stocks"):
        targets(t, params("none", 1.0), [D + timedelta(days=1)])


@pytest.mark.parametrize("signal, frac", [("none", 0.2), ("skew", 1.0), ("skew", 0.0)])
def test_bad_portfolio_fails(signal, frac):
    with pytest.raises(ValidationError):
        Portfolio(signal=signal, top_frac=frac)


@pytest.mark.parametrize("name, signal, offset", [("m119_cps", "call_put_spread", 0), ("m119_ew_off15", "none", 15),
                                                  ("m119_ovr_off5", "option_volume", 5)])
def test_configs_load(name, signal, offset):
    cfg = load_strategy_config(ROOT / f"strategies/options_book/configs/{name}.yaml", ROOT)
    assert isinstance(cfg.params, Params) and cfg.params.portfolio.signal == signal
    assert cfg.params.decision_offset_sessions == offset
