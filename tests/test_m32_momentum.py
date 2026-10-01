"""M32: conditional volatility targeting; the picks shrink only when the shadow book's last month was in its top volatility state."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest
from pydantic import ValidationError
from test_m5_momentum import _days
from test_m19_momentum import _m19

from mb.config.loader import load_strategy_config
from mb.engine.rebalance import Target
from mb.strategy.momentum.params import ParamsM29, ParamsM32, VolStates
from mb.strategy.momentum.targets import vol_state_scales, with_book_scale

ROOT = Path(__file__).resolve().parents[1]


def _m32(vol_states: dict | None, **portfolio) -> ParamsM32:
    p = _m19({"GOLD": 0.1}, portfolio={"top_n": 2, "hold_rank_max": 2}).model_dump()
    p["portfolio"] |= {"fixed_trend_sessions": None, "rotation": None, "vol_states": vol_states} | portfolio
    p["exits"] |= {"book_stop_frac": None}
    p["ranking"] |= {"order": "score"}
    return ParamsM32.model_validate(p)


def _vs(**over) -> VolStates:
    return VolStates.model_validate({"vol_sessions": 5, "high_quantile": 0.8, "min_history_months": 3} | over)


def test_m29_configs_keep_their_model_and_m32_configs_route_to_m32():
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m29_lowvol_gold20_b2.yaml", ROOT).params) is ParamsM29
    for q in ("q80", "q75"):
        cfg = load_strategy_config(ROOT / f"strategies/momentum/configs/m32_cvt_{q}_gold20_b2.yaml", ROOT)
        assert type(cfg.params) is ParamsM32 and cfg.params.portfolio.vol_states.vol_sessions == 21


def test_vol_states_are_validated():
    good = {"vol_sessions": 5, "high_quantile": 0.8, "min_history_months": 3}
    with pytest.raises(ValidationError, match="high_quantile"):
        _m32(good | {"high_quantile": 1.0})
    with pytest.raises(ValidationError, match="resize_held true"):
        _m32(good, resize_held=False)
    assert _m32(None).portfolio.vol_states is None


def _shadow(rets: list[float]) -> tuple[pl.DataFrame, list]:
    days = _days(len(rets) + 1)
    eq = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(rets)]))
    return pl.DataFrame({"date": days, "equity": eq}), days


def test_scale_is_one_in_calm_months_and_target_over_vol_in_the_top_state():
    # Noisy 1% days, a calm week to day 40 (the lowest vol so far), then a week of 4% days (the highest).
    g = np.random.default_rng(0)
    rets = list(g.normal(0, 0.01, 35)) + list(g.normal(0, 0.002, 5)) + list(g.normal(0, 0.04, 5))
    shadow, days = _shadow(rets)
    stg = {days[i]: Target({"A": 1.0}, 1.0) for i in (0, 10, 20, 30, 40, 45)}
    k = vol_state_scales(shadow, stg, _vs(), [days[40], days[45]])
    assert k[days[40]] == 1.0
    r = np.diff(np.log(shadow["equity"].to_numpy()))
    want = np.std(r[1:45], ddof=1) / np.std(r[40:45], ddof=1)
    assert k[days[45]] == pytest.approx(want) and k[days[45]] < 0.5


def test_scale_needs_history_and_ignores_windows_before_the_first_investment():
    g = np.random.default_rng(1)
    rets = [0.0] * 10 + list(g.normal(0, 0.01, 20)) + list(g.normal(0, 0.002, 10))  # day 30 is the calmest
    shadow, days = _shadow(rets)
    stg = {days[0]: Target({}, 0.0), days[10]: Target({"A": 1.0}, 1.0), days[20]: Target({"A": 1.0}, 1.0),
           days[30]: Target({"A": 1.0}, 1.0)}
    with pytest.raises(ValueError, match="2 months of shadow volatility"):
        vol_state_scales(shadow, stg, _vs(), [days[30]])  # day 10's window starts before the first investment
    assert vol_state_scales(shadow, stg, _vs(min_history_months=2), [days[30]]) == {days[30]: 1.0}


def test_with_book_scale_shrinks_the_picks_and_keeps_the_fixed_weights():
    t = Target({"A": 0.4, "B": 0.4, "GOLD": 0.2}, 1.0)
    got = with_book_scale(t, 0.5, {"GOLD"})
    assert got.weights == {"A": 0.2, "B": 0.2, "GOLD": 0.2} and got.gross == pytest.approx(0.6)
    assert with_book_scale(t, 1.0, {"GOLD"}) is t
    assert with_book_scale(Target({"A": 1.0}, 1.0), 0.0, set()) == Target({}, 0.0, frozenset())
