"""M127: MSCI-style momentum score tilt (src/mb/strategy/momentum/targets.py)."""
from datetime import date, timedelta

import polars as pl
import pytest

from mb.strategy.momentum.params import Ranking
from mb.strategy.momentum.targets import score_tilts


def test_tilt_is_one_plus_z_above_the_mean_and_inverse_below():
    # lookback 1 / skip 0, plain return: A +30%, B +10%, C -10%, D -30% -> mean 0, population sd sqrt(0.05)
    closes = {"A": [1.0, 1.3], "B": [1.0, 1.1], "C": [1.0, 0.9], "D": [1.0, 0.7]}
    panel = pl.DataFrame([{"date": date(2020, 1, 1) + timedelta(days=i), "symbol": s, "adj_close": c[i]}
                          for s, c in closes.items() for i in range(2)])
    d = date(2020, 1, 2)
    t = score_tilts(panel, Ranking(lookback_sessions=1, skip_sessions=0, score="return"), {d: list(closes)}, 3.0)
    za = 0.3 / 0.05 ** 0.5
    assert t[d]["A"] == pytest.approx(1 + za) and t[d]["D"] == pytest.approx(1 / (1 + za))
    assert score_tilts(panel, Ranking(lookback_sessions=1, skip_sessions=0, score="return"), {d: list(closes)},
                       1.0)[d]["A"] == pytest.approx(2.0)  # clipped at 1
