"""M121: long-term winners among the ranked names (src/mb/strategy/momentum/targets.py)."""
from datetime import date, timedelta

import polars as pl
import pytest
from pydantic import ValidationError

from mb.strategy.momentum.params import LongReversal
from mb.strategy.momentum.targets import long_winners


def _panel(closes: dict[str, list[float]]) -> pl.DataFrame:
    return pl.DataFrame([{"date": date(2020, 1, 1) + timedelta(days=i), "symbol": s, "adj_close": c}
                         for s, cs in closes.items() for i, c in enumerate(cs)])


def test_top_fraction_of_ranked_names_by_return_from_from_to_to():
    # from 4 / to 1 sessions ago at the last date (index 5): A 100->300, B 100->200, C 100->110, D unranked 100->900
    p = _panel({"A": [1, 100, 1, 1, 300, 1], "B": [1, 100, 1, 1, 200, 1], "C": [1, 100, 1, 1, 110, 1],
                "D": [1, 100, 1, 1, 900, 1], "E": [1, 1, 1, 1, 1, 1]})
    d = date(2020, 1, 6)
    lr = LongReversal(from_sessions=4, to_sessions=1, drop_frac=0.5)
    assert long_winners(p, lr, {d: ["C", "B", "A"]}) == {d: {"A": -1.0, "B": -1.0}}  # ceil(0.5 * 3) = 2, D not ranked
    assert long_winners(p, lr.model_copy(update={"drop_frac": 0.2}), {d: ["C", "B", "A"]}) == {d: {"A": -1.0}}


def test_names_without_history_are_not_counted():
    p = _panel({"A": [1, 100, 1, 1, 300, 1]})
    d0, d = date(2020, 1, 4), date(2020, 1, 6)
    lr = LongReversal(from_sessions=4, to_sessions=1, drop_frac=0.5)
    assert long_winners(p, lr, {d0: ["A"], d: ["A"]}) == {d0: {}, d: {"A": -1.0}}


def test_bad_settings_fail():
    with pytest.raises(ValidationError):
        LongReversal(from_sessions=252, to_sessions=756, drop_frac=0.1)
    with pytest.raises(ValidationError):
        LongReversal(from_sessions=756, to_sessions=252, drop_frac=1.0)
