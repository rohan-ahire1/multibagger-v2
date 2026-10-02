"""M81: a stop's proceeds re-spread over the names still held (docs/research/m81.md)."""
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
from mb.strategy.momentum.params import ParamsM81

ROOT = Path(__file__).resolve().parents[1]


def _m81(stop: float | None, to: str | None, respread: bool) -> ParamsM81:
    d = _m57(None, 0).model_dump()
    d["fixed_weights"] = None
    d["exits"] |= {"stop_loss_frac": stop, "stop_proceeds_to": to, "stop_trailing": False, "stop_vol_sessions": None,
                   "stop_vol_mult": None, "stop_market_symbol": None, "stop_market_frac": None, "stop_respread": respread}
    return ParamsM81.model_validate(d)


def test_stopped_money_buys_the_held_names_pro_rata():
    days = _days(6)
    # A and B 50/50 bought at 100 on day 1. A closes at 85 on day 2 (stopped), sold at day 3's open 80. B opens day 3
    # at 120: all of A's proceeds buy B there.
    bars = _bars({"A": [100.0, 100.0, 85.0, 80.0, 80.0, 80.0], "B": [100.0, 100.0, 110.0, 120.0, 120.0, 120.0]}, days)
    tg = {days[0]: Target({"A": 1.0, "B": 1.0}, 1.0)}
    r = simulate_targets(tg, bars, days, market(), 1000.0, 0.10, None, False, None, None, True)
    e = r.equity
    assert e["cash"][3] == pytest.approx(0.0, abs=1e-9)
    assert e["equity"][-1] == pytest.approx(500.0 / 100 * 120 + 500.0 / 100 * 80, rel=1e-12)
    assert r.fills.filter(r.fills["side"] == "buy").height == 3
    with pytest.raises(ValueError, match="exclusive"):
        simulate_targets(tg, bars, days, market(), 1000.0, 0.10, "B", False, None, None, True)


def test_the_option_is_validated_routed_and_refused_by_paper():
    with pytest.raises(ValidationError, match="needs stop_loss_frac"):
        _m81(None, None, True)
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m81_resp_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM81
    with pytest.raises(ValueError, match="exits.stop_respread"):
        check_supported(cfg.params)
