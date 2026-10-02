"""M79: stops that fire only in a falling market (docs/research/m79.md)."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from test_m2_engine import market
from test_m5_momentum import _bars, _days
from test_m57_momentum import _m57

from mb.config.loader import load_strategy_config
from mb.engine.rebalance import Target, simulate_targets
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM79

ROOT = Path(__file__).resolve().parents[1]


def _m79(stop: float | None, sym: str | None, g: float | None) -> ParamsM79:
    d = _m57(None, 0).model_dump()
    d["exits"] |= {"stop_loss_frac": stop, "stop_proceeds_to": None, "stop_trailing": False, "stop_vol_sessions": None,
                   "stop_vol_mult": None, "stop_market_symbol": sym, "stop_market_frac": g}
    return ParamsM79.model_validate(d)


def test_the_stop_waits_for_the_market_to_be_below_its_rebalance_open():
    days = _days(8)
    # A closes 11% down on day 3 while the market M is above its rebalance open (100): held. On day 5 M closes at 99
    # with A still below its stop: sold at day 6's open.
    a = [100.0, 100.0, 95.0, 89.0, 88.0, 87.0, 86.0, 86.0]
    m = [100.0, 100.0, 101.0, 102.0, 101.0, 99.0, 98.0, 98.0]
    bars = _bars({"A": a, "M": m}, days)
    tg = {days[0]: Target({"A": 1.0}, 1.0)}
    plain = simulate_targets(tg, bars, days, market(), 1000.0, 0.10)
    cond = simulate_targets(tg, bars, days, market(), 1000.0, 0.10, None, False, None, ("M", 0.0))
    assert plain.holdings["exit_date"][0] == days[4]
    assert cond.holdings["status"].to_list() == ["stopped"] and cond.holdings["exit_date"][0] == days[6]
    deep = simulate_targets(tg, bars, days, market(), 1000.0, 0.10, None, False, None, ("M", 0.05))
    assert deep.holdings["status"].to_list() == ["open"]


def test_the_option_is_validated_routed_and_refused_by_paper():
    with pytest.raises(ValidationError, match="go together"):
        _m79(0.1, "M", None)
    with pytest.raises(ValidationError, match="needs stop_loss_frac"):
        _m79(None, "M", 0.0)
    with pytest.raises(ValidationError, match=r"\[0, 1\)"):
        _m79(0.1, "M", -0.1)
    with pytest.raises(ValueError, match="has no bars"):
        simulate_targets({}, _bars({"A": [1.0]}, _days(1)), _days(1), market(), 1.0, 0.1, None, False, None, ("M", 0.0))
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m79_mkt0_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM79
    with pytest.raises(ValueError, match="exits.stop_market_symbol"):
        check_supported(cfg.params)
