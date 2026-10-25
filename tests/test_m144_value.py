"""M144: trailing earnings, market caps and the value book's targets (mb.data.fundamentals, mb.strategy.value)."""
from datetime import date

import polars as pl
import pytest

from mb.data import fundamentals
from mb.strategy.value.params import Params, Universe
from mb.strategy.value.run import targets


def _filings(rows):
    return pl.DataFrame(rows, schema=["symbol", "seq", "period_end", "avail", "net_profit", "paid_up", "face_value"],
                        orient="row")


QS = [date(2019, 3, 31), date(2019, 6, 30), date(2019, 9, 30), date(2019, 12, 31)]


def _rows(sym, profits, shares=10.0):
    return [(sym, f"{sym}{i}", pe, date(2020, 1, 20) if i == 3 else pe, npf, shares * 10.0, 10.0)
            for i, (pe, npf) in enumerate(zip(QS, profits))]


def test_ttm_needs_four_quarters_and_freshness():
    f = _filings(_rows("A", [1.0, 2.0, 3.0, 4.0]) + _rows("B", [1.0, 1.0, 1.0, 1.0])[1:])
    d = date(2020, 1, 31)
    assert fundamentals.ttm_profit(f, [d], 200)[d] == {"A": 10.0}           # B has three quarters
    assert fundamentals.ttm_profit(f, [date(2020, 1, 10)], 200)[date(2020, 1, 10)] == {}  # Dec quarter not filed:
    # Sep is the latest known, and June 2018 is missing
    assert fundamentals.ttm_profit(f, [date(2021, 1, 31)], 200)[date(2021, 1, 31)] == {}  # stale


def _panel(d, closes):
    return pl.DataFrame({"date": [d] * len(closes), "symbol": list(closes), "close": list(closes.values()),
                         "adj_factor": [1.0] * len(closes), "turnover": [1e9] * len(closes),
                         "series": ["EQ"] * len(closes), "security_id": ["isin:INE"] * len(closes)})


def test_market_caps_and_value_targets_pick_highest_positive_yield():
    d = QS[-1]
    rows = _rows("A", [1.0] * 4) + _rows("B", [5.0] * 4) + _rows("C", [-1.0] * 4) + _rows("D", [2.0] * 4)
    rows = [(s, q, pe, pe, n, pu, fv) for s, q, pe, av, n, pu, fv in rows]  # all known by the quarter end
    f = _filings(rows)
    panel = _panel(d, {"A": 100.0, "B": 100.0, "C": 100.0, "D": 100.0, "E": 100.0})
    assert fundamentals.market_caps(f, panel, [d], 200)[d] == {s: pytest.approx(1000.0) for s in "ABCD"}
    u = Universe(allowed_series=["EQ"], min_price_inr=50, min_adv_inr=1e7, adv_window_sessions=1, exclude_fund_units=True)
    p = Params(universe=u, results_raw_dir="x", max_age_days=200, score="earnings_yield", top_n=2,
               decision_offset_sessions=0, initial_capital=1e6)
    t = targets(panel, f, p, d, d, frozenset({"D"}))
    assert set(t[d].weights) == {"B", "A"} and t[d].gross == 1.0   # D is a fund unit, C loses money, E has no data


def test_stable_growth_needs_eight_quarters_all_recent_positive_and_growth():
    qs = [date(2018, 3, 31), date(2018, 6, 30), date(2018, 9, 30), date(2018, 12, 31)] + QS
    def rows(sym, profits):
        return [(sym, f"{sym}{i}", pe, pe, npf, 100.0, 10.0) for i, (pe, npf) in enumerate(zip(qs, profits))]
    f = _filings(rows("G", [1, 1, 1, 1, 1, 1, 1, 2]) + rows("L", [1, 1, 1, 1, 2, -1, 3, 3])
                 + rows("F", [2, 2, 2, 2, 1, 1, 1, 1]) + rows("S", [1, 1, 1, 1, 1, 1, 1]))
    d = date(2020, 1, 31)
    # G grows; L has a loss quarter; F shrinks; S lacks the eighth quarter (Dec 2019)
    assert fundamentals.stable_growth(f, [d], 200)[d] == {"G"}
