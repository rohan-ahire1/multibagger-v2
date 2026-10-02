"""M12: MAX (lottery) filter and absolute momentum, and config routing."""
from __future__ import annotations

from pathlib import Path

import pytest
from test_m5_momentum import _days, _frame, _params
from test_m10_momentum import _prices, _wiggle
from test_m11_momentum import _m11

from mb.config.loader import load_strategy_config
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM11, ParamsM12
from mb.strategy.momentum.targets import ranked, targets

ROOT = Path(__file__).resolve().parents[1]


def _m12(**over) -> ParamsM12:
    p = _m11().model_dump()
    p["ranking"] |= {"max_filter_frac": None, "max_window_sessions": 5}
    p["portfolio"] |= {"min_momentum": None}
    for k, v in over.items():
        p[k] = p[k] | v
    return ParamsM12.model_validate(p)


def test_m11_configs_keep_their_model_and_m12_configs_route_to_m12():
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m11_invvol_b2.yaml", ROOT).params) is ParamsM11
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m12_control_b1.yaml", ROOT).params) is ParamsM12


def test_paper_trading_refuses_m12_options_but_not_the_control():
    check_supported(_m12())
    for k, v in (("ranking", {"max_filter_frac": 0.1}), ("portfolio", {"min_momentum": 0.0})):
        with pytest.raises(ValueError, match="M12"):
            check_supported(_m12(**{k: v}))


def test_m12_with_every_option_off_equals_the_plain_strategy():
    days = _days(90)
    panel = _frame({s: _prices(_wiggle(90, k)) for k, s in enumerate(["A", "B", "C"])}, days)
    port = {"top_n": 2, "hold_rank_max": 2}
    assert targets(panel, _params(portfolio=port), days[30], days[-1]) == targets(panel, _m12(portfolio=port), days[30], days[-1])


def test_max_filter_drops_the_names_with_the_biggest_recent_one_day_jump():
    days = _days(40)
    # LOTTO had a +12% day in the last 5 sessions; with frac 0.3 of 4 names, ceil(1.2) = 2 are dropped:
    # LOTTO and then the next-biggest one-day return (FAST's steady 1%/day beats SLOW's and FLAT's).
    lotto = [100.0 * 1.004 ** i * (1.12 if i >= 37 else 1.0) for i in range(40)]
    panel = _frame({"LOTTO": lotto,
                    "FAST": [100.0 * 1.01 ** i for i in range(40)], "SLOW": [100.0 * 1.003 ** i for i in range(40)],
                    "FLAT": [100.0 * 1.001 ** i for i in range(40)]}, days)
    base = {"lookback_sessions": 20, "skip_sessions": 5}
    d = days[-1]
    plain = _m12(ranking=base)
    assert ranked(panel, plain.universe, plain.ranking, d, d)[d][0] == "FAST"
    p = _m12(ranking=base | {"max_filter_frac": 0.3})
    assert ranked(panel, p.universe, p.ranking, d, d)[d] == ["SLOW", "FLAT"]


def test_absolute_momentum_keeps_empty_slots_in_cash():
    days = _days(60)
    panel = _frame({"UP": [100.0 * 1.003 ** i for i in range(60)], "DOWN": [100.0 * 0.998 ** i for i in range(60)],
                    "DOWN2": [100.0 * 0.997 ** i for i in range(60)]}, days)
    p = _m12(portfolio={"top_n": 2, "hold_rank_max": 2, "min_momentum": 0.0})
    t = targets(panel, p, days[30], days[-1])
    assert all(list(v.weights) == ["UP"] and v.gross == pytest.approx(0.5) for v in t.values())
    none = _m12(portfolio={"top_n": 2, "hold_rank_max": 2, "min_momentum": 0.10})
    assert all(v.weights == {} and v.gross == 0.0 for v in targets(panel, none, days[30], days[-1]).values())
