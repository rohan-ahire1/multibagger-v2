"""M124: the no-trade band on held names (src/mb/engine/rebalance.py)."""
from datetime import date, timedelta

import polars as pl
from test_m2_engine import market

from mb.engine.rebalance import Target, simulate_targets


def _run(band: float | None) -> pl.DataFrame:
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(4)]
    # A rises 10% between the two decisions, B is flat: at the second decision A is ~5% over its half, B ~5% under.
    px = {"A": [10.0, 10.0, 11.0, 11.0], "B": [10.0, 10.0, 10.0, 10.0]}
    bars = pl.DataFrame([{"date": d, "symbol": s, "open": p[i], "close": p[i]} for s, p in px.items()
                         for i, d in enumerate(days)])
    t = {days[0]: Target({"A": 1.0, "B": 1.0}, 1.0, resize_band=band),
         days[2]: Target({"A": 1.0, "B": 1.0}, 1.0, resize_band=band)}
    return simulate_targets(t, bars, days, market(), 1000.0).fills


def test_within_band_held_names_are_not_traded():
    assert _run(None).filter(pl.col("date") == date(2020, 1, 4)).height == 2  # resized: sell A, buy B
    assert _run(0.10).filter(pl.col("date") == date(2020, 1, 4)).height == 0  # both within 10%
    assert _run(0.01).filter(pl.col("date") == date(2020, 1, 4)).height == 2  # outside 1%: resized
