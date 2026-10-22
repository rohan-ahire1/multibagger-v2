"""M129: momentum acceleration in the rank (src/mb/strategy/momentum/targets.py)."""
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest
from pydantic import ValidationError

from mb.strategy.momentum.params import RankingM129, Universe
from mb.strategy.momentum.targets import accelerations, ranked

U = Universe(allowed_series=["EQ"], min_price_inr=0.0, min_adv_inr=0.0, adv_window_sessions=1, exclude_fund_units=False)


def _panel(closes: dict[str, list[float]]) -> pl.DataFrame:
    return pl.DataFrame([{"date": date(2020, 1, 1) + timedelta(days=i), "symbol": s, "adj_close": c, "close": c,
                          "turnover": 1.0, "series": "EQ", "security_id": f"isin:INE{s}"}
                         for s, cs in closes.items() for i, c in enumerate(cs)])


def _ranking(w: float | None) -> RankingM129:
    return RankingM129(lookback_sessions=6, skip_sessions=1, score="return", second_lookback_sessions=None,
                       high_window_sessions=None, residual_beta_sessions=None, residual_benchmark_symbol="X",
                       frog_candidates_per_slot=None, max_filter_frac=None, max_window_sessions=21, order="score",
                       return_part="total", score_risk="stdev", accel_rank_weight=w)


def test_acceleration_is_the_quadratic_coefficient_of_the_window_ending_skip_rows_back():
    t = np.arange(8, dtype=float)
    closes = list(np.exp(0.1 + 0.02 * t + 0.003 * t * t))
    closes[-1] = 1e6  # the skipped row does not enter the fit
    p = _panel({"A": closes})
    d = date(2020, 1, 8)
    got = accelerations(p, 6, 1, [d, date(2020, 1, 5)])
    assert got[(d, "A")] == pytest.approx(0.003)
    assert (date(2020, 1, 5), "A") not in got  # fewer than lookback rows before it


def test_blend_puts_the_accelerating_name_first():
    # B has the higher 5-row return; A rises late (convex), B early (concave).
    a = [100, 100, 101, 103, 110, 130, 1]
    b = [100, 120, 127, 129, 130, 131, 1]
    p = _panel({"A": a, "B": b})
    d = date(2020, 1, 7)
    assert ranked(p, U, _ranking(0.75), d, d)[d] == ["A", "B"]
    assert ranked(p, U, _ranking(None), d, d)[d] == ["B", "A"]


def test_bad_weight_fails():
    with pytest.raises(ValidationError):
        _ranking(1.0)
