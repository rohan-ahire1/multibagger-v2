"""M19: fixed-weight symbols (a gold sleeve) held beside the momentum picks."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from test_m5_momentum import _days, _frame
from test_m10_momentum import _prices, _wiggle
from test_m13_momentum import _m13

from mb.config.loader import load_strategy_config
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM13, ParamsM19
from mb.strategy.momentum.targets import targets

ROOT = Path(__file__).resolve().parents[1]


def _m19(fixed: dict[str, float], **over) -> ParamsM19:
    p = _m13(**over).model_dump()
    p["portfolio"] |= {"fixed_weights": fixed}
    return ParamsM19.model_validate(p)


def _panel():
    days = _days(90)
    prices = {s: _prices(_wiggle(90, k)) for k, s in enumerate(["A", "B", "C"])}
    prices["GOLD"] = [100.0 * 0.995 ** i for i in range(90)]  # falling: never ranked into the top 2
    return _frame(prices, days), days


def test_m16_configs_keep_their_model_and_m19_configs_route_to_m19():
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m16_invvol_b2.yaml", ROOT).params) is ParamsM13
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m19_gold20_invvol_b2.yaml", ROOT).params) is ParamsM19


def test_fixed_weights_must_be_positive_and_leave_room_for_the_picks():
    for bad in ({"GOLD": 0.0}, {"GOLD": 1.0}, {"GOLD": 0.6, "SILVER": 0.4}):
        with pytest.raises(ValidationError, match="fixed_weights"):
            _m19(bad)


def test_the_fixed_symbol_gets_its_weight_and_the_picks_keep_their_proportions():
    panel, days = _panel()
    port = {"top_n": 2, "hold_rank_max": 2}
    plain = targets(panel, _m13(portfolio=port), days[30], days[-1])
    got = targets(panel, _m19({"GOLD": 0.2}, portfolio=port), days[30], days[-1])
    assert got.keys() == plain.keys()
    for d, t in got.items():
        base = plain[d]
        total = sum(base.weights.values())
        assert t.weights["GOLD"] == 0.2 and t.gross == base.gross
        assert sum(t.weights.values()) == pytest.approx(1.0)
        for s, w in base.weights.items():
            assert t.weights[s] == pytest.approx(w / total * 0.8)


def test_no_fixed_weights_equals_the_m13_strategy():
    panel, days = _panel()
    port = {"top_n": 2, "hold_rank_max": 2}
    assert targets(panel, _m19({}, portfolio=port), days[30], days[-1]) == targets(panel, _m13(portfolio=port), days[30], days[-1])


def test_a_fixed_symbol_that_is_also_picked_is_an_error():
    panel, days = _panel()
    with pytest.raises(ValueError, match="also picked"):
        targets(panel, _m19({"A": 0.2}, portfolio={"top_n": 3, "hold_rank_max": 3}), days[30], days[-1])


def test_paper_trading_refuses_fixed_weights():
    check_supported(_m19({}))
    with pytest.raises(ValueError, match="fixed_weights"):
        check_supported(_m19({"GOLD": 0.2}))
