"""M118: market-level F&O signals (src/mb/data/market.py, params.py, targets.py hook)."""
import math
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from mb.config.loader import load_strategy_config
from mb.data import market
from mb.strategy.momentum.params import MarketSignal, ParamsM118

ROOT = Path(__file__).resolve().parents[1]
RANKED = {"kind": "fii_futures", "raw_dir": "x", "option_symbol": None, "rv_symbol": None, "rv_sessions": None,
          "window_sessions": 250, "min_pct": 0.2}


def series(values, start=date(2020, 1, 1)):
    return pl.DataFrame({"avail": [start + timedelta(days=i) for i in range(len(values))], "value": values})


def test_ranked_on_uses_the_latest_usable_value_and_its_window():
    s = series([5.0, 4.0, 3.0, 2.0, 6.0])  # avail 1-5 Jan
    got = market.ranked_on(s, [date(2020, 1, 2), date(2020, 1, 4), date(2020, 1, 5), date(2020, 1, 7)], 3, 0.34)
    # 2 Jan: window not full -> on; 4 Jan: 2 vs [4, 3, 2] -> none below -> off; 5 Jan and 7 Jan: 6 vs [3, 2, 6] -> 2/3
    assert got == {date(2020, 1, 2): True, date(2020, 1, 4): False, date(2020, 1, 5): True, date(2020, 1, 7): True}


def test_before_the_data_is_on_and_stale_data_fails():
    s = series([1.0, 2.0], start=date(2020, 1, 10))
    assert market.ranked_on(s, [date(2020, 1, 5)], 2, 0.5) == {date(2020, 1, 5): True}
    with pytest.raises(ValueError, match="latest value"):
        market.ranked_on(s, [date(2020, 1, 11) + timedelta(days=market.STALE_DAYS + 1)], 2, 0.5)


def test_vrp_compares_vix_variance_with_realised_variance():
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(4)]
    panel = pl.DataFrame({"date": days, "symbol": ["NB"] * 4, "adj_close": [100.0, 110.0, 99.0, 99.0]})
    rv = math.log(1.1) ** 2 + math.log(0.9) ** 2  # the two returns to 3 Jan (the 1 Jan diff is null)
    vix = pl.DataFrame({"avail": [days[2]], "value": [100.0 * math.sqrt(12 * rv) + 0.01]})
    assert market.vrp_on(vix, panel, "NB", 2, [days[2]]) == {days[2]: True}
    vix = vix.with_columns(pl.col("value") - 0.02)
    assert market.vrp_on(vix, panel, "NB", 2, [days[2], days[3]]) == {days[2]: False, days[3]: True}  # 4 Jan: rv drops
    assert market.vrp_on(vix.with_columns(avail=pl.lit(days[3])), panel, "NB", 2, [days[2]]) == {days[2]: True}  # no VIX yet
    with pytest.raises(ValueError, match="realised variance"):
        market.vrp_on(vix, panel, "NB", 2, [days[1]])


def test_loaders_lag_the_evening_files(tmp_path):
    (tmp_path / "fo").mkdir(), (tmp_path / "oi").mkdir(), (tmp_path / "vix").mkdir()
    d = date(2020, 3, 2)
    pl.DataFrame({"d": [d] * 4, "instrument": ["OPTIDX", "OPTIDX", "OPTIDX", "OPTSTK"], "sym": ["NIFTY"] * 3 + ["X"],
                  "opt": ["PE", "CE", "PE", "PE"], "oi": [30.0, 20.0, 10.0, 99.0]}).write_parquet(tmp_path / "fo/a.parquet")
    assert market.load_pcr(tmp_path / "fo", "NIFTY").rows() == [(d + timedelta(days=1), 2.0)]
    pl.DataFrame({"d": [d, d], "client_type": ["FII", "DII"], "fut_idx_long": [1.0, 5.0],
                  "fut_idx_short": [3.0, 5.0]}).write_parquet(tmp_path / "oi/a.parquet")
    assert market.load_fii_long_share(tmp_path / "oi").rows() == [(d + timedelta(days=1), 0.25)]
    pl.DataFrame({"EOD_TIMESTAMP": ["02-MAR-2020"], "EOD_CLOSE_INDEX_VAL": [20.5]}).write_parquet(tmp_path / "vix/a.parquet")
    assert market.load_vix(tmp_path / "vix").rows() == [(d, 20.5)]
    with pytest.raises(FileNotFoundError):
        market.load_vix(tmp_path)


@pytest.mark.parametrize("change", [{"kind": "pcr"}, {"min_pct": None}, {"rv_sessions": 21}, {"min_pct": 1.0},
                                    {"kind": "vrp"}, {"option_symbol": "NIFTY"}])
def test_bad_market_signal_fails(change):
    with pytest.raises(ValidationError):
        MarketSignal(**{**RANKED, **change})


@pytest.mark.parametrize("name, kind", [("m118_vrp", "vrp"), ("m118_pcr_off5", "pcr"), ("m118_fii_off15", "fii_futures")])
def test_configs_load_as_m118(name, kind):
    cfg = load_strategy_config(ROOT / f"strategies/momentum/configs/{name}.yaml", ROOT)
    assert isinstance(cfg.params, ParamsM118) and cfg.params.regime.market_signal is not None
    assert cfg.params.regime.market_signal.kind == kind and cfg.params.regime.risk_off_months == []
