"""M117: "sell in May" risk-off months (src/mb/strategy/momentum/targets.py, params.py)."""
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from mb.config.loader import load_strategy_config
from mb.strategy.momentum.params import ParamsM117, RegimeM117
from mb.strategy.momentum.targets import seasonal_off

ROOT = Path(__file__).resolve().parents[1]
REGIME = {"enabled": True, "benchmark_symbol": "JUNIORBEES", "sma_sessions": 200, "risk_off_gross": 0.5,
          "risk_off_symbol": "GOLDBEES", "extra_benchmark_symbols": [], "breadth_min_frac": None, "band_frac": None}


def test_seasonal_off_forces_listed_months_and_keeps_the_rest():
    regime = {date(2020, 3, 31): True, date(2020, 4, 30): True, date(2020, 9, 30): False, date(2020, 10, 30): False,
              date(2020, 11, 30): True}
    assert seasonal_off(regime, [4, 5, 6, 7, 8, 9]) == {date(2020, 3, 31): True, date(2020, 4, 30): False,
                                                       date(2020, 9, 30): False, date(2020, 10, 30): False,
                                                       date(2020, 11, 30): True}


@pytest.mark.parametrize("months, enabled", [([4, 4], True), ([0], True), ([13], True), ([4], False)])
def test_bad_months_fail(months, enabled):
    with pytest.raises(ValidationError):
        RegimeM117(**{**REGIME, "enabled": enabled, "risk_off_months": months})


def test_halloween_config_loads_as_m117():
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m117_halloween.yaml", ROOT)
    assert isinstance(cfg.params, ParamsM117) and cfg.params.regime.risk_off_months == [4, 5, 6, 7, 8, 9]
