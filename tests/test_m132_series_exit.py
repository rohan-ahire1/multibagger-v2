"""M132: sell picks moved out of the allowed series between decisions (src/mb/strategy/momentum/targets.py)."""
from datetime import date

import polars as pl

from mb.engine.rebalance import Target
from mb.strategy.momentum.targets import series_exits


def _panel(rows: list[tuple[int, str, str]]) -> pl.DataFrame:
    return pl.DataFrame([{"date": date(2020, 1, d), "symbol": s, "series": se} for d, s, se in rows])


def test_first_off_session_drops_the_name_and_keeps_the_rest():
    rows = [(d, "A", "EQ") for d in range(1, 11)] + [(d, "GOLD", "EQ") for d in range(1, 11)]
    rows += [(d, "B", "EQ") for d in (1, 2, 3)] + [(d, "B", "BE") for d in range(4, 11)]
    rows += [(d, "C", "EQ") for d in range(1, 11)] + [(5, "C", "BE")]  # an extra BE row beside EQ is not a move
    out = {date(2020, 1, 1): Target({"A": 1.0, "B": 1.0, "C": 1.0, "GOLD": 1.0}, 1.0),
           date(2020, 1, 8): Target({"A": 1.0, "C": 1.0, "GOLD": 1.0}, 1.0)}
    got = series_exits(_panel(rows), out, ["EQ"], {"GOLD"}, date(2020, 1, 10))
    assert sorted(got) == [date(2020, 1, 1), date(2020, 1, 4), date(2020, 1, 8)]
    t = got[date(2020, 1, 4)]
    assert t.weights == {"A": 1.0, "C": 1.0, "GOLD": 1.0} and t.keep_size == frozenset({"A", "C", "GOLD"})


def test_a_move_on_the_next_decision_is_left_to_that_decision():
    rows = [(d, "A", "EQ") for d in range(1, 8)] + [(8, "A", "BE")]
    out = {date(2020, 1, 1): Target({"A": 1.0}, 1.0), date(2020, 1, 8): Target({}, 1.0)}
    assert sorted(series_exits(_panel(rows), out, ["EQ"], set(), date(2020, 1, 8))) == [date(2020, 1, 1), date(2020, 1, 8)]


def test_skipped_funds_are_never_dropped():
    rows = [(1, "GOLD", "EQ"), (2, "GOLD", "BE")]
    out = {date(2020, 1, 1): Target({"GOLD": 1.0}, 1.0)}
    assert list(series_exits(_panel(rows), out, ["EQ"], {"GOLD"}, date(2020, 1, 3))) == [date(2020, 1, 1)]
