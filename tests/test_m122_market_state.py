"""M122: market state from the benchmark's own past level (src/mb/strategy/momentum/targets.py)."""
from datetime import date, timedelta

import polars as pl
import pytest
from pydantic import ValidationError

from mb.strategy.momentum.params import RegimeM122
from mb.strategy.momentum.targets import market_state_up


def _panel(closes: list[float]) -> pl.DataFrame:
    return pl.DataFrame([{"date": date(2020, 1, 1) + timedelta(days=i), "symbol": "B", "adj_close": c}
                         for i, c in enumerate(closes)] + [{"date": date(2020, 1, 1), "symbol": "X", "adj_close": 1.0}])


def test_up_when_at_or_above_the_level_n_sessions_back():
    p = _panel([10, 12, 10, 11, 9])
    d = [date(2020, 1, 3), date(2020, 1, 4), date(2020, 1, 5)]
    assert market_state_up(p, "B", 2, d) == {d[0]: True, d[1]: False, d[2]: False}


def test_missing_history_is_an_error():
    with pytest.raises(ValueError):
        market_state_up(_panel([10, 12, 10]), "B", 2, [date(2020, 1, 2)])


def test_needs_regime_enabled():
    with pytest.raises(ValidationError):
        RegimeM122(enabled=False, benchmark_symbol="B", sma_sessions=200, risk_off_gross=0.5, risk_off_symbol=None,
                   extra_benchmark_symbols=[], breadth_min_frac=None, band_frac=None, risk_off_months=[],
                   market_signal=None, state_sessions=756)
