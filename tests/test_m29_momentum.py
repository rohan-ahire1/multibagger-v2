"""M29: rank by low volatility instead of momentum."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from test_m5_momentum import _days, _frame
from test_m19_momentum import _m19

from mb.config.loader import load_strategy_config
from mb.strategy.momentum.params import ParamsM27, ParamsM29
from mb.strategy.momentum.targets import ranked

ROOT = Path(__file__).resolve().parents[1]


def _m29(order: str, **ranking) -> ParamsM29:
    p = _m19({"GOLD": 0.1}, portfolio={"top_n": 2, "hold_rank_max": 2}).model_dump()
    p["portfolio"] |= {"fixed_trend_sessions": None, "rotation": None}
    p["exits"] |= {"book_stop_frac": None}
    p["ranking"] |= {"score": "return_over_vol", "order": order} | ranking
    return ParamsM29.model_validate(p)


def test_m27_configs_keep_their_model_and_m29_configs_route_to_m29():
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m27_rot_gold_b2.yaml", ROOT).params) is ParamsM27
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m29_lowvol_gold20_b2.yaml", ROOT).params) is ParamsM29


def test_low_vol_is_validated():
    with pytest.raises(ValidationError, match="needs score return_over_vol"):
        _m29("low_vol", score="return")
    with pytest.raises(ValidationError, match="no other ranking option: max_filter_frac"):
        _m29("low_vol", max_filter_frac=0.1)
    assert _m29("score", max_filter_frac=0.1).ranking.order == "score"


def test_low_vol_ranks_the_calmest_first_whatever_the_trend():
    n = 40
    days = _days(n)
    calm_down = [100.0 * (0.999 if i % 2 else 0.9985) ** i for i in range(n)]  # falls, small daily moves
    wild_up = [100.0 * (1.08 if i % 2 else 0.95) ** (i // 2) * (1.08 if i % 2 else 1.0) for i in range(n)]
    mid = [100.0 * (1.02 if i % 2 else 0.99) ** i for i in range(n)]
    panel = _frame({"CALM": calm_down, "WILD": wild_up, "MID": mid}, days)
    d = days[-1]
    low = _m29("low_vol", lookback_sessions=20, skip_sessions=0)
    assert ranked(panel, low.universe, low.ranking, d, d)[d] == ["CALM", "MID", "WILD"]
    mom = _m29("score", lookback_sessions=20, skip_sessions=0)
    assert ranked(panel, mom.universe, mom.ranking, d, d)[d][-1] == "CALM"


def test_htp_scores_the_run_up_to_the_peak_not_the_fall_since():
    n = 30
    days = _days(n)
    # PEAKED: +40% then falls back to +5%; STEADY: +20% straight; both measured over 20 sessions to the decision date.
    peaked = [100.0] * 10 + [100.0 * 1.4 ** (k / 10) for k in range(1, 11)] + [140.0 - 3.5 * k for k in range(1, 11)]
    steady = [100.0] * 10 + [100.0 * 1.2 ** (k / 20) for k in range(1, 21)]
    panel = _frame({"PEAKED": peaked, "STEADY": steady}, days)
    d = days[-1]
    htp = _m29("htp", score="return", lookback_sessions=20, skip_sessions=0)
    assert ranked(panel, htp.universe, htp.ranking, d, d)[d] == ["PEAKED", "STEADY"]
    mom = _m29("score", score="return", lookback_sessions=20, skip_sessions=0)
    assert ranked(panel, mom.universe, mom.ranking, d, d)[d] == ["STEADY", "PEAKED"]
    with pytest.raises(ValidationError, match="order htp takes no other ranking option"):
        _m29("htp", second_lookback_sessions=10)
