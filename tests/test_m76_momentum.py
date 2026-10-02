"""M76: trailing and volatility-widened stops (docs/research/m76.md)."""
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
from mb.strategy.momentum.params import ParamsM76


def _m76(stop: float | None, trail: bool, n: int | None, k: float | None) -> ParamsM76:
    d = _m57(None, 0).model_dump()
    d["exits"] |= {"stop_loss_frac": stop, "stop_proceeds_to": None, "stop_trailing": trail,
                   "stop_vol_sessions": n, "stop_vol_mult": k}
    return ParamsM76.model_validate(d)


ROOT = Path(__file__).resolve().parents[1]


def test_trailing_stop_ratchets_from_the_highest_close_since_the_rebalance():
    days = _days(8)
    # Bought at 100. Rises to 120, then closes at 107 on day 4: 10.8% below 120 (trailing fires), 7% above 100 (fixed not).
    a = [100.0, 100.0, 110.0, 120.0, 107.0, 105.0, 106.0, 108.0]
    bars = _bars({"A": a}, days)
    tg = {days[0]: Target({"A": 1.0}, 1.0)}
    fixed = simulate_targets(tg, bars, days, market(), 1000.0, 0.10)
    trail = simulate_targets(tg, bars, days, market(), 1000.0, 0.10, None, True)
    assert fixed.holdings["status"].to_list() == ["open"]
    h = trail.holdings
    assert h["status"].to_list() == ["stopped"] and h["exit_date"][0] == days[5]


def test_vol_stop_widens_for_a_volatile_name_and_never_tightens():
    days = _days(12)
    # A swings +-5% a day before the decision (std ~0.054, x3 = 16%), then falls 12% after the rebalance: kept with the
    # vol stop, stopped with the plain 10% stop. B is calm: its stop stays 10%.
    a = [100.0, 105.0, 99.75, 104.74, 99.5, 104.47, 99.25, 99.25, 92.0, 87.3, 88.0, 89.0]
    b = [100.0] * 7 + [100.0, 95.0, 89.0, 89.0, 89.0]
    bars = _bars({"A": a, "B": b}, days)
    tg = {days[6]: Target({"A": 0.5, "B": 0.5}, 1.0)}
    plain = simulate_targets(tg, bars, days, market(), 1000.0, 0.10)
    vol = simulate_targets(tg, bars, days, market(), 1000.0, 0.10, None, False, (5, 3.0))
    st = lambda r: dict(zip(r.holdings["symbol"], r.holdings["status"]))
    assert st(plain) == {"A": "stopped", "B": "stopped"}
    assert st(vol) == {"A": "open", "B": "stopped"}


def test_the_options_are_validated_routed_and_refused_by_paper():
    with pytest.raises(ValidationError, match="go together"):
        _m76(0.1, False, 63, None)
    with pytest.raises(ValidationError, match="need stop_loss_frac"):
        _m76(None, True, None, None)
    with pytest.raises(ValidationError, match=">= 2"):
        _m76(0.1, False, 1, 4.5)
    with pytest.raises(ValueError, match="need a stop"):
        simulate_targets({}, _bars({"A": [1.0]}, _days(1)), _days(1), market(), 1.0, None, None, True)
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m76_trail10_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM76
    with pytest.raises(ValueError, match="exits.stop_trailing"):
        check_supported(cfg.params)
