"""M57: decide every n sessions instead of at month-ends (docs/research/m57.md)."""
from __future__ import annotations

from pathlib import Path

import math

import pytest
from pydantic import ValidationError
from test_m5_momentum import _days, _frame
from test_m55_momentum import _m55

from mb.config.loader import load_strategy_config
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM57
from mb.strategy.momentum.targets import month_ends, targets

ROOT = Path(__file__).resolve().parents[1]


def _m57(every: int | None, phase: int, offset: int = 0) -> ParamsM57:
    d = _m55("total").model_dump()
    d["schedule"] |= {"every_sessions": every, "phase_session": phase, "decision_offset_sessions": offset}
    d["portfolio"] |= {"fixed_weights": {}}
    return ParamsM57.model_validate(d)


def test_decisions_fall_every_n_sessions_from_the_phase_and_null_is_monthly():
    days = _days(120)
    series = {s: [100.0 * math.exp(0.001 * i + 0.1 * math.sin(i / 15 + k)) for i in range(120)] for k, s in enumerate("ABCDE")}
    panel = _frame(series, days)
    start, end = days[20], days[-1]
    in_period = [d for d in days if start <= d <= end]
    assert sorted(targets(panel, _m57(7, 3), start, end)) == in_period[3::7]
    assert sorted(targets(panel, _m57(None, 0), start, end)) == month_ends(panel, start, end)


def test_the_option_is_validated_routed_and_refused_by_paper():
    with pytest.raises(ValidationError, match="phase_session"):
        _m57(5, 5)
    with pytest.raises(ValidationError, match="phase_session needs"):
        _m57(None, 1)
    with pytest.raises(ValidationError, match="decision_offset_sessions 0"):
        _m57(5, 0, offset=2)
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m57_e10_h35_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM57
    with pytest.raises(ValueError, match="schedule.every_sessions"):
        check_supported(cfg.params)
    check_supported(load_strategy_config(ROOT / "strategies/momentum/configs/m57_control_b2.yaml", ROOT).params)
