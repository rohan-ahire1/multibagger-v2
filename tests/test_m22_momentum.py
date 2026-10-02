"""M22: the fixed (gold) sleeve is held only while its own trend is up; otherwise its weight goes to the picks."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from test_m5_momentum import _days, _frame
from test_m10_momentum import _prices, _wiggle
from test_m13_momentum import _m13
from test_m19_momentum import _m19

from mb.config.loader import load_strategy_config
from mb.strategy.momentum.params import ParamsM19, ParamsM22
from mb.strategy.momentum.targets import targets, trend_up

ROOT = Path(__file__).resolve().parents[1]
PORT = {"top_n": 2, "hold_rank_max": 2}


def _m22(n: int | None) -> ParamsM22:
    p = _m19({"GOLD": 0.2}, portfolio=PORT).model_dump()
    p["portfolio"] |= {"fixed_trend_sessions": n}
    p["exits"] |= {"book_stop_frac": None}
    return ParamsM22.model_validate(p)


def _panel():
    days = _days(120)
    prices = {s: _prices(_wiggle(120, k)) for k, s in enumerate(["A", "B", "C"])}
    prices["GOLD"] = [100.0 * (0.995 ** i if i < 60 else 0.995 ** 60 * 1.004 ** (i - 60)) for i in range(120)]
    return _frame(prices, days, {"GOLD": "isin:INFGOLD"}), days  # a fund: never ranked


def test_m19_configs_keep_their_model_and_m22_configs_route_to_m22():
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m19_gold20_invvol_b2.yaml", ROOT).params) is ParamsM19
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m22_gold20_trend252_b2.yaml", ROOT).params) is ParamsM22


def test_fixed_trend_sessions_must_be_positive():
    with pytest.raises(ValidationError, match="fixed_trend_sessions"):
        _m22(0)


def test_gold_is_held_only_while_it_is_above_its_close_n_sessions_earlier():
    panel, days = _panel()
    up = trend_up(panel, ["GOLD"], 20, days[20:])
    assert not up[(days[59], "GOLD")] and up[(days[119], "GOLD")]
    got = targets(panel, _m22(20), days[30], days[-1])
    with_gold = targets(panel, _m19({"GOLD": 0.2}, portfolio=PORT), days[30], days[-1])
    no_gold = targets(panel, _m13(portfolio=PORT), days[30], days[-1])
    for d, t in got.items():
        assert t == (with_gold[d] if up[(d, "GOLD")] else no_gold[d])
    assert any(up[(d, "GOLD")] for d in got) and not all(up[(d, "GOLD")] for d in got)


def test_no_trend_rule_equals_m19():
    panel, days = _panel()
    assert targets(panel, _m22(None), days[30], days[-1]) == targets(panel, _m19({"GOLD": 0.2}, portfolio=PORT), days[30], days[-1])


def test_missing_history_is_an_error():
    panel, days = _panel()
    with pytest.raises(ValueError, match="fixed_trend_sessions"):
        trend_up(panel, ["GOLD"], 200, days[30:])
