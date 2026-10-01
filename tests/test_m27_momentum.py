"""M27: each month the book's share goes to whichever of the shadow book and the rotation assets did best recently."""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError
from test_m5_momentum import _days, _frame
from test_m19_momentum import _m19

from mb.config.loader import load_strategy_config
from mb.engine.rebalance import Target
from mb.strategy.momentum.params import ParamsM19, ParamsM27, Rotation
from mb.strategy.momentum.targets import rotation_shares, with_rotation

ROOT = Path(__file__).resolve().parents[1]
PORT = {"top_n": 2, "hold_rank_max": 2}


def _rot(**over) -> dict:
    return {"assets": ["GOLD"], "lookbacks_sessions": [5, 10], "top_k": 1, "cash_floor": False} | over


def _m27(rotation: dict | None, fixed: dict[str, float] | None = None) -> ParamsM27:
    p = _m19(fixed or {}, portfolio=PORT).model_dump() if fixed else _m19({"GOLD": 0.1}, portfolio=PORT).model_dump()
    p["portfolio"] |= {"fixed_weights": fixed or {}, "fixed_trend_sessions": None, "rotation": rotation}
    p["exits"] |= {"book_stop_frac": None}
    return ParamsM27.model_validate(p)


def _shadow(values: list[float]) -> tuple[pl.DataFrame, list]:
    days = _days(len(values))
    return pl.DataFrame({"date": days, "equity": values}), days


def test_m19_configs_keep_their_model_and_m27_configs_route_to_m27():
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m19_gold20_invvol_b2.yaml", ROOT).params) is ParamsM19
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m27_rot_gold_b2.yaml", ROOT).params) is ParamsM27


def test_rotation_is_validated():
    with pytest.raises(ValidationError, match="fixed_weights must be empty"):
        _m27(_rot(), fixed={"GOLD": 0.2})
    with pytest.raises(ValidationError, match="top_k"):
        _m27(_rot(top_k=3))
    with pytest.raises(ValidationError, match="lookbacks"):
        _m27(_rot(lookbacks_sessions=[]))
    assert _m27(None).portfolio.rotation is None


def test_shares_average_the_winner_over_lookbacks():
    # Book rises steadily; gold falls for 15 sessions then jumps: over 5 sessions gold wins, over 10 the book wins.
    book = [100.0 * 1.01 ** i for i in range(20)]
    gold = [100.0 * 0.99 ** i for i in range(15)] + [100.0 * 0.99 ** 14 * 1.03 ** k for k in range(1, 6)]
    shadow, days = _shadow(book)
    panel = _frame({"GOLD": gold}, days, {"GOLD": "isin:INFGOLD"})
    got = rotation_shares(shadow, panel, Rotation.model_validate(_rot()), [days[12], days[19]])
    assert got[days[12]] == {"": 1.0, "GOLD": 0.0}
    assert got[days[19]] == {"": 0.5, "GOLD": 0.5}


def test_cash_floor_sends_a_losing_winner_to_cash_and_unlisted_assets_are_skipped():
    book = [100.0 * 0.99 ** i for i in range(20)]  # falling
    shadow, days = _shadow(book)
    gold = [None] * 8 + [100.0 * 0.995 ** i for i in range(12)]  # listed late, falls less than the book
    panel = _frame({"GOLD": gold}, days, {"GOLD": "isin:INFGOLD"}).drop_nulls("adj_close")
    r = Rotation.model_validate(_rot(lookbacks_sessions=[5, 10], cash_floor=True))
    got = rotation_shares(shadow, panel, r, [days[15]])[days[15]]
    assert got == {"": 0.0, "GOLD": 0.0}  # 5: gold wins but fell -> cash; 10: gold not listed, book wins but fell -> cash
    r2 = Rotation.model_validate(_rot(lookbacks_sessions=[5, 10]))
    assert rotation_shares(shadow, panel, r2, [days[15]])[days[15]] == {"": 0.5, "GOLD": 0.5}


def test_missing_shadow_history_is_an_error():
    shadow, days = _shadow([100.0] * 8)
    panel = _frame({"GOLD": [1.0] * 8}, days, {"GOLD": "isin:INFGOLD"})
    with pytest.raises(ValueError, match="no equity 10 sessions"):
        rotation_shares(shadow, panel, Rotation.model_validate(_rot()), [days[7]])


def test_with_rotation_scales_picks_and_adds_assets():
    t = Target({"A": 1.0, "B": 3.0}, 1.0)
    got = with_rotation(t, {"": 0.5, "GOLD": 0.25})
    assert got.weights == {"A": 0.125, "B": 0.375, "GOLD": 0.25} and got.gross == pytest.approx(0.75)
    assert with_rotation(t, {"": 0.0, "GOLD": 0.0}) == Target({}, 0.0, frozenset())
    assert with_rotation(t, {"": 1.0, "GOLD": 0.0}).weights == {"A": 0.25, "B": 0.75}
    with pytest.raises(ValueError, match="also picked"):
        with_rotation(Target({"GOLD": 1.0}, 1.0), {"": 0.5, "GOLD": 0.5})
