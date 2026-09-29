"""M11: decision-date offset, stop-loss and inverse-vol weights, and config routing."""
from __future__ import annotations

import math
from pathlib import Path

import pytest
from test_m2_engine import market
from test_m5_momentum import _bars, _days, _frame, _params
from test_m10_momentum import _prices, _wiggle

from mb.config.loader import load_strategy_config
from mb.engine.rebalance import Target, simulate_targets
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM10, ParamsM11
from mb.strategy.momentum.targets import decision_dates, month_ends, targets

ROOT = Path(__file__).resolve().parents[1]


def _m11(**over) -> ParamsM11:
    p = _params().model_dump()
    p["ranking"] |= {"second_lookback_sessions": None, "high_window_sessions": None, "residual_beta_sessions": None,
                     "residual_benchmark_symbol": "IDX", "frog_candidates_per_slot": None}
    p["portfolio"] |= {"resize_held": True, "max_per_sector": None, "weighting": "equal", "inverse_vol_sessions": 10}
    p["sizing"] = {"vol_target_annual": None, "vol_benchmark_symbol": "IDX", "vol_window_sessions": 10}
    p["schedule"] = {"decision_offset_sessions": 0}
    p["exits"] = {"stop_loss_frac": None}
    for k, v in over.items():
        p[k] = p[k] | v
    return ParamsM11.model_validate(p)


def test_m10_configs_keep_their_model_and_m11_configs_route_to_m11():
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m10_control_b1.yaml", ROOT).params) is ParamsM10
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m11_control_b1.yaml", ROOT).params) is ParamsM11


def test_paper_trading_refuses_m11_options_but_not_the_control():
    check_supported(_m11())
    for k, v in (("schedule", {"decision_offset_sessions": 5}), ("exits", {"stop_loss_frac": 0.1}),
                 ("portfolio", {"weighting": "inverse_vol"})):
        with pytest.raises(ValueError, match="M11"):
            check_supported(_m11(**{k: v}))


def test_bad_values_are_refused():
    with pytest.raises(ValueError, match="stop_loss_frac"):
        _m11(exits={"stop_loss_frac": 1.5})
    with pytest.raises(ValueError, match="decision_offset_sessions"):
        _m11(schedule={"decision_offset_sessions": -1})


def test_m11_with_every_option_off_equals_the_plain_strategy():
    days = _days(90)
    panel = _frame({s: _prices(_wiggle(90, k)) for k, s in enumerate(["A", "B", "C"])}, days)
    port = {"top_n": 2, "hold_rank_max": 2}
    assert targets(panel, _params(portfolio=port), days[30], days[-1]) == targets(panel, _m11(portfolio=port), days[30], days[-1])


def test_decision_offset_counts_sessions_back_from_each_month_end():
    days = _days(70)  # 2020-01-01 .. 2020-04-07
    panel = _frame({"A": [100.0] * 70}, days)
    ends = month_ends(panel, days[0], days[-1])
    got = decision_dates(panel, days[0], days[-1], 3)
    by_month = {}
    for d in days:
        by_month.setdefault((d.year, d.month), []).append(d)
    assert got == [m[-4] for m in by_month.values() if len(m) > 3]
    assert decision_dates(panel, days[0], days[-1], 0) == ends
    tg = targets(panel, _m11(schedule={"decision_offset_sessions": 3}, ranking={"lookback_sessions": 5, "skip_sessions": 1}),
                 days[10], days[-1])
    assert list(tg) == [d for d in got if d >= days[10]]


def test_inverse_vol_weights_calm_names_more():
    days = _days(60)
    calm = _prices([0.002 * math.sin(i) + 0.003 for i in range(60)])
    wild = _prices([0.02 * math.sin(i) + 0.003 for i in range(60)])
    panel = _frame({"CALM": calm, "WILD": wild}, days)
    p = _m11(portfolio={"top_n": 2, "hold_rank_max": 2, "weighting": "inverse_vol", "inverse_vol_sessions": 10})
    t = targets(panel, p, days[30], days[-1])
    w = next(iter(t.values())).weights
    assert w["CALM"] / w["WILD"] == pytest.approx(10.0, rel=0.05)


def test_stop_sells_at_the_next_open_after_a_close_below_the_stop_and_waits_for_the_rebalance():
    days = _days(8)
    # Bought at day 1's open (100). Day 3 closes at 89 (<= 90): sold at day 4's open (88). Day 6 is the next rebalance.
    a = [100.0, 100.0, 95.0, 89.0, 88.0, 91.0, 93.0, 95.0]
    bars = _bars({"A": a}, days)
    tg = {days[0]: Target({"A": 1.0}, 1.0), days[5]: Target({"A": 1.0}, 1.0)}
    res = simulate_targets(tg, bars, days, market(), 1000.0, 0.10)
    h = res.holdings.sort("entry_date")
    assert h["status"].to_list() == ["stopped", "open"]
    assert h["exit_date"][0] == days[4]
    assert h["sold"][0] == pytest.approx(880.0)
    assert h["entry_date"][1] == days[6]
    eq = res.equity.sort("date")
    assert eq["cash"][5] == pytest.approx(880.0) and eq["invested_value"][5] == 0.0
    none = simulate_targets(tg, bars, days, market(), 1000.0, None)
    assert none.holdings["status"].to_list() == ["open"]


def test_stop_reference_resets_at_each_rebalance():
    days = _days(8)
    # Rebalanced at day 1 (open 100) and day 4 (open 85). Day 5 closes at 80: 6% below 85, 20% below 100 -> no stop at 10%.
    a = [100.0, 100.0, 95.0, 90.5, 85.0, 80.0, 82.0, 84.0]
    bars = _bars({"A": a}, days)
    tg = {days[0]: Target({"A": 1.0}, 1.0), days[3]: Target({"A": 1.0}, 1.0)}
    res = simulate_targets(tg, bars, days, market(), 1000.0, 0.10)
    assert res.holdings["status"].to_list() == ["open"]
