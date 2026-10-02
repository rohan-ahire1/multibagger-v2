"""M82: a stopped name is bought back when it closes at its reference again (docs/research/m82.md)."""
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
from mb.strategy.momentum.params import ParamsM82


ROOT = Path(__file__).resolve().parents[1]


def _m82(stop: float | None, trailing: bool, reentry: bool) -> ParamsM82:
    d = _m57(None, 0).model_dump()
    d["exits"] |= {"stop_loss_frac": stop, "stop_proceeds_to": None, "stop_trailing": trailing,
                   "stop_vol_sessions": None, "stop_vol_mult": None, "stop_market_symbol": None,
                   "stop_market_frac": None, "stop_respread": False, "stop_reentry": reentry}
    return ParamsM82.model_validate(d)


def test_a_stopped_name_is_bought_back_at_its_reference():
    days = _days(8)
    # Bought at 100 on day 1; closes 88 on day 2 (stopped), sold at 88 on day 3; closes 101 on day 4 (>= 100), bought
    # back at day 5's open 102 with the 880 proceeds.
    a = [100.0, 100.0, 88.0, 88.0, 101.0, 102.0, 110.0, 110.0]
    bars = _bars({"A": a}, days)
    tg = {days[0]: Target({"A": 1.0}, 1.0)}
    r = simulate_targets(tg, bars, days, market(), 1000.0, 0.10, None, False, None, None, False, True)
    assert r.holdings["status"].to_list() == ["stopped", "open"]
    assert r.holdings["entry_date"][1] == days[5]
    assert r.equity["equity"][-1] == pytest.approx(880.0 / 102.0 * 110.0, rel=1e-12)
    plain = simulate_targets(tg, bars, days, market(), 1000.0, 0.10)
    assert plain.equity["equity"][-1] == pytest.approx(880.0, rel=1e-12)


def test_the_option_is_validated_routed_and_refused_by_paper():
    with pytest.raises(ValidationError, match="plain stop_loss_frac"):
        _m82(0.1, True, True)
    with pytest.raises(ValueError, match="plain stop"):
        simulate_targets({}, _bars({"A": [1.0]}, _days(1)), _days(1), market(), 1.0, None, None, False, None, None,
                         False, True)
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m82_reent_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM82
    with pytest.raises(ValueError, match="exits.stop_reentry"):
        check_supported(cfg.params)
