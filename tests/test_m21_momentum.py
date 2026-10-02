"""M21: a stop on the whole book of picks, measured from its highest close since the decision date."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from test_m5_momentum import _days, _frame
from test_m19_momentum import _m19

from mb.config.loader import load_strategy_config
from mb.engine.rebalance import Target
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM19, ParamsM21
from mb.strategy.momentum.targets import _with_fixed, book_stops

ROOT = Path(__file__).resolve().parents[1]


def _m21(frac: float | None) -> ParamsM21:
    p = _m19({"GOLD": 0.2}).model_dump()
    p["exits"] |= {"book_stop_frac": frac}
    return ParamsM21.model_validate(p)


def test_m19_configs_keep_their_model_and_m21_configs_route_to_m21():
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m19_gold20_invvol_b2.yaml", ROOT).params) is ParamsM19
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m21_gold20_bstop10_b2.yaml", ROOT).params) is ParamsM21


def test_book_stop_frac_must_be_a_fraction():
    for bad in (0.0, 1.0, -0.1):
        with pytest.raises(ValidationError, match="book_stop_frac"):
            _m21(bad)


def test_the_stop_fires_once_at_the_first_close_below_the_peak_and_waits_for_the_next_decision():
    days = _days(30)
    # A: 100 -> 140 (book 1.2) by day 4, then 110 on day 6 (book 1.05 <= 0.9 x 1.2 = 1.08): stopped although above the start.
    a = [100.0, 110.0, 120.0, 130.0, 140.0, 125.0, 110.0, 90.0, 80.0] + [80.0] * 21
    panel = _frame({"A": a, "B": [100.0] * 30}, days)
    out = {days[0]: Target({"A": 1.0, "B": 1.0}, 1.0), days[20]: Target({"A": 1.0}, 1.0)}
    got = book_stops(panel, out, 0.10, days[-1])
    assert list(got) == [days[0], days[6], days[20]]
    assert got[days[6]] == Target({}, 1.0, frozenset())
    assert book_stops(panel, out, 0.50, days[-1]) == out


def test_a_stopped_book_keeps_its_fixed_symbols_at_their_weight():
    assert _with_fixed(Target({}, 1.0, frozenset()), {"GOLD": 0.2}) == Target({"GOLD": 0.2}, 0.2, frozenset())


def test_paper_trading_refuses_the_book_stop():
    p = _m21(None).model_dump()
    p["portfolio"]["fixed_weights"] = {}
    check_supported(ParamsM21.model_validate(p))
    with pytest.raises(ValueError, match="book_stop_frac"):
        check_supported(_m21(0.1))
