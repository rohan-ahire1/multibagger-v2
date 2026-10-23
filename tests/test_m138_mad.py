"""M138: moving-average distance in the rank (src/mb/strategy/momentum/targets.py)."""
from datetime import date, timedelta

import polars as pl
import pytest
from pydantic import ValidationError

from mb.strategy.momentum.params import RankingM138, Universe
from mb.strategy.momentum.targets import ranked

U = Universe(allowed_series=["EQ"], min_price_inr=0.0, min_adv_inr=0.0, adv_window_sessions=1, exclude_fund_units=False)


def _panel(closes: dict[str, list[float]]) -> pl.DataFrame:
    return pl.DataFrame([{"date": date(2020, 1, 1) + timedelta(days=i), "symbol": s, "adj_close": c, "close": c,
                          "turnover": 1.0, "series": "EQ", "security_id": f"isin:INE{s}"}
                         for s, cs in closes.items() for i, c in enumerate(cs)])


def _ranking(w: float | None, short: int | None = 2, long: int | None = 6, accel: float | None = None) -> RankingM138:
    return RankingM138(lookback_sessions=6, skip_sessions=1, score="return", second_lookback_sessions=None,
                       high_window_sessions=None, residual_beta_sessions=None, residual_benchmark_symbol="X",
                       frog_candidates_per_slot=None, max_filter_frac=None, max_window_sessions=21, order="score",
                       return_part="total", score_risk="stdev", accel_rank_weight=accel, mad_rank_weight=w,
                       mad_short_sessions=short if w is not None else None,
                       mad_long_sessions=long if w is not None else None)


def test_mad_uses_the_last_rows_including_the_skipped_one():
    # B: higher return over the score window (rows 1..6 back to 1 back); A: jumps on the decision row itself, which
    # only MAD sees (2-row mean / 6-row mean ending at the decision).
    a = [100, 100, 100, 100, 100, 101, 200]
    b = [100, 110, 120, 130, 140, 150, 150]
    p = _panel({"A": a, "B": b})
    d = date(2020, 1, 7)
    assert ranked(p, U, _ranking(None), d, d)[d] == ["B", "A"]
    assert ranked(p, U, _ranking(1.0), d, d)[d] == ["A", "B"]   # MAD A = 150.5/116.8 > B = 150/131.7


def test_half_blend_ties_fall_back_to_the_symbol():
    a = [100, 100, 100, 100, 100, 101, 200]
    b = [100, 110, 120, 130, 140, 150, 150]
    p = _panel({"B": b, "A": a})
    d = date(2020, 1, 7)
    assert ranked(p, U, _ranking(0.5), d, d)[d] == ["A", "B"]   # one rank each: equal keys, symbol order


def test_names_without_long_history_are_not_ranked():
    p = _panel({"A": [100, 101, 102, 103, 104, 105, 106]})
    d = date(2020, 1, 7)
    assert ranked(p, U, _ranking(1.0, 2, 8), d, d)[d] == []


@pytest.mark.parametrize("kw", [dict(w=0.0), dict(w=1.5), dict(w=0.5, short=6, long=6), dict(w=0.5, accel=0.5)])
def test_bad_settings_fail(kw):
    with pytest.raises(ValidationError):
        _ranking(**kw)


def test_partial_settings_fail():
    with pytest.raises(ValidationError):
        RankingM138(lookback_sessions=6, skip_sessions=1, score="return", second_lookback_sessions=None,
                    high_window_sessions=None, residual_beta_sessions=None, residual_benchmark_symbol="X",
                    frog_candidates_per_slot=None, max_filter_frac=None, max_window_sessions=21, order="score",
                    return_part="total", score_risk="stdev", accel_rank_weight=None, mad_rank_weight=0.5,
                    mad_short_sessions=None, mad_long_sessions=200)
