"""M128: return over downside deviation as the ranking score (src/mb/strategy/momentum/targets.py)."""
import math
from datetime import date, timedelta

import polars as pl
import pytest
from pydantic import ValidationError

from mb.strategy.momentum.params import Ranking, RankingM128, Universe
from mb.strategy.momentum.targets import ranked

U = Universe(allowed_series=["EQ"], min_price_inr=0.0, min_adv_inr=0.0, adv_window_sessions=1, exclude_fund_units=False)


def _ranking(risk: str) -> RankingM128:
    return RankingM128(lookback_sessions=4, skip_sessions=0, score="return_over_vol", second_lookback_sessions=None,
                       high_window_sessions=None, residual_beta_sessions=None, residual_benchmark_symbol="X",
                       frog_candidates_per_slot=None, max_filter_frac=None, max_window_sessions=21, order="score",
                       return_part="total", score_risk=risk)


def _panel(closes: dict[str, list[float]]) -> pl.DataFrame:
    return pl.DataFrame([{"date": date(2020, 1, 1) + timedelta(days=i), "symbol": s, "adj_close": c, "close": c,
                          "turnover": 1.0, "series": "EQ", "security_id": f"isin:INE{s}"}
                         for s, cs in closes.items() for i, c in enumerate(cs)])


def test_downside_deviation_prefers_the_name_whose_swings_are_up():
    # Same 4-session return (+21%) and the same set of daily moves; A's big move is up, B's is down.
    a = [100.0, 130.0, 117.0, 117.0, 121.0]
    b = [100.0, 77.0, 100.1, 110.1, 121.0]
    p = _panel({"A": a, "B": b})
    d = date(2020, 1, 5)
    down = ranked(p, U, _ranking("downside"), d, d)[d]
    assert down == ["A", "B"]
    # the downside score of A by hand: only the two falling days count
    lr = [math.log(a[i + 1] / a[i]) for i in range(4)]
    dd = math.sqrt(sum(min(x, 0.0) ** 2 for x in lr) / 4)
    assert dd == pytest.approx(math.sqrt(math.log(117 / 130) ** 2 / 4))


def test_stdev_is_unchanged_from_the_plain_score():
    p = _panel({"A": [100.0, 130.0, 117.0, 117.0, 121.0], "B": [100.0, 77.0, 100.1, 110.1, 121.0],
                "C": [100.0, 101.0, 102.0, 103.0, 104.0]})
    d = date(2020, 1, 5)
    plain = Ranking(lookback_sessions=4, skip_sessions=0, score="return_over_vol")
    assert ranked(p, U, _ranking("stdev"), d, d) == ranked(p, U, plain, d, d)


def test_downside_needs_the_vol_score():
    with pytest.raises(ValidationError):
        _ranking("downside").model_validate({**_ranking("downside").model_dump(), "score": "return"})
