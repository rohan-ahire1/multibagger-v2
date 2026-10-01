"""M46: decide only every n-th month (docs/research/m46.md)."""
from __future__ import annotations

from pathlib import Path

import math

import pytest
from pydantic import ValidationError
from test_m5_momentum import _days, _frame
from test_m40_momentum import _m40

from mb.config.loader import load_strategy_config
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM40, ParamsM46
from mb.strategy.momentum.targets import targets

ROOT = Path(__file__).resolve().parents[1]


def _m46(every: int, phase: int) -> ParamsM46:
    d = _m40(None).model_dump()
    d["schedule"] |= {"every_months": every, "phase_month": phase}
    d["portfolio"] |= {"fixed_weights": {}}
    return ParamsM46.model_validate(d)


def _panel():
    # Five names whose leadership rotates (phase-shifted waves on a drift), ten months of sessions.
    days = _days(210)
    series = {s: [100.0 * math.exp(0.001 * i + 0.1 * math.sin(i / 15 + k)) for i in range(210)] for k, s in enumerate("ABCDE")}
    return _frame(series, days), days[0], days[-1]


def test_only_every_nth_month_decides_and_the_first_decision_matches_the_monthly_book():
    panel, start, end = _panel()
    base = targets(panel, _m46(1, 0), start, end)
    assert len(base) >= 6
    q = targets(panel, _m46(3, 1), start, end)
    assert q and set(q) <= set(base) and all(d.month % 3 == 1 for d in q)
    assert {d for d in base if d.month % 3 == 1} == set(q)
    assert all(q[d] == base[d] for d in sorted(q)[:1])  # the first decision has nothing held before it


def test_the_option_is_validated_routed_and_refused_by_paper():
    with pytest.raises(ValidationError, match="phase_month"):
        _m46(3, 3)
    with pytest.raises(ValidationError, match="every_months"):
        _m46(0, 0)
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m46_q3p0_deliv40_gold20_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM46
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m40_deliv40_gold20_b2.yaml", ROOT).params) is ParamsM40
    with pytest.raises(ValueError, match="schedule.every_months"):
        check_supported(cfg.params)
    check_supported(load_strategy_config(ROOT / "strategies/momentum/configs/m46_q1_control_b2.yaml", ROOT).params)
