"""M75: stop-loss proceeds bought into a fixed-weight symbol at the same open (docs/research/m75.md)."""
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
from mb.strategy.momentum.params import ParamsM57, ParamsM75

ROOT = Path(__file__).resolve().parents[1]


def _m75(stop: float | None, to: str | None, fixed: dict[str, float]) -> ParamsM75:
    d = _m57(None, 0).model_dump()
    d["portfolio"] |= {"fixed_weights": fixed}
    d["exits"] |= {"stop_loss_frac": stop, "stop_proceeds_to": to}
    return ParamsM75.model_validate(d)


def test_stop_proceeds_buy_the_park_symbol_at_the_same_open_and_it_is_never_stopped():
    days = _days(8)
    # A: bought at day 1's open (100), closes at 89 on day 3, sold at day 4's open (88). G falls 20% but is never stopped.
    a = [100.0, 100.0, 95.0, 89.0, 88.0, 91.0, 93.0, 95.0]
    g = [50.0, 50.0, 45.0, 40.0, 40.0, 41.0, 42.0, 43.0]
    bars = _bars({"A": a, "G": g}, days)
    tg = {days[0]: Target({"A": 0.5, "G": 0.5}, 1.0), days[5]: Target({"A": 0.5, "G": 0.5}, 1.0)}
    res = simulate_targets(tg, bars, days, market(), 1000.0, 0.10, "G")
    f = res.fills.filter(res.fills["date"] == days[4]).sort("side")
    assert f["symbol"].to_list() == ["G", "A"] and f["side"].to_list() == ["buy", "sell"]
    assert f["cash_flow"][0] == pytest.approx(-440.0) and f["shares"][0] == pytest.approx(440.0 / 40.0)
    eq = res.equity.sort("date")
    assert eq["cash"][4] == pytest.approx(0.0)
    h = res.holdings
    assert h.filter(h["symbol"] == "G")["status"].to_list() == ["open"]
    plain = simulate_targets(tg, bars, days, market(), 1000.0, 0.10)
    assert plain.equity.sort("date")["cash"][4] == pytest.approx(840.0)  # without parking, G is stopped too


def test_the_option_is_validated_routed_and_refused_by_paper():
    with pytest.raises(ValidationError, match="needs stop_loss_frac"):
        _m75(None, "G", {"G": 0.2})
    with pytest.raises(ValidationError, match="must be in portfolio.fixed_weights"):
        _m75(0.1, "G", {})
    assert _m75(0.1, "G", {"G": 0.2}).exits.stop_proceeds_to == "G"
    with pytest.raises(ValueError, match="needs a stop"):
        simulate_targets({}, _bars({"A": [1.0]}, _days(1)), _days(1), market(), 1.0, None, "G")
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m75_s10_park_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM75
    with pytest.raises(ValueError, match="exits.stop_proceeds_to"):
        check_supported(cfg.params)
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m57_control_b2.yaml", ROOT).params) is ParamsM57
