"""M134 live prep (M132 note): held names moved off the allowed series are listed for a person (paper.off_series)."""
from datetime import date

import polars as pl

from mb.live.paper import Book, DataView, Position, off_series


def _view(rows: list[tuple[str, date, str]]) -> DataView:
    panel = pl.DataFrame(rows, schema={"symbol": pl.String, "date": pl.Date, "series": pl.String}, orient="row")
    return DataView("x", "", panel, {}, pl.DataFrame(), {})


def _pos() -> Position:
    return Position(1, date(2026, 1, 1), 1.0, 0.0, 1.0, date(2026, 1, 5))


def test_lists_held_names_whose_newest_row_is_off_series_with_the_run_start():
    d1, d2, d3, d4 = date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)
    view = _view([("A", d1, "EQ"), ("A", d2, "BE"), ("A", d3, "BE"), ("A", d4, "EQ"),  # d4 after the book's date
                  ("B", d1, "BE"), ("B", d2, "EQ"), ("B", d3, "EQ"),                   # back on EQ
                  ("C", d3, "BE"),                                                      # not held
                  ("D", d1, "BZ"), ("D", d3, "BZ")])
    book = Book(d3, 0.0, {"A": _pos(), "B": _pos(), "D": _pos()})
    assert off_series(book, view, ["EQ"]) == ["A: series BE since 2026-01-02", "D: series BZ since 2026-01-01"]


def test_an_empty_or_unstarted_book_lists_nothing():
    view = _view([("A", date(2026, 1, 1), "BE")])
    assert off_series(Book(None, 0.0, {"A": _pos()}), view, ["EQ"]) == []
    assert off_series(Book(date(2026, 1, 1), 0.0, {}), view, ["EQ"]) == []
