"""M114: results-meeting reaction signal (src/mb/data/results.py)."""
from datetime import date

import polars as pl
import pytest

from mb.data import results

D = [date(2020, 1, k) for k in (6, 7, 8, 9, 10, 13)]


def panel():
    a = [100.0, 100.0, 110.0, 110.0, 120.0, 120.0]  # meeting on the 8th: pre = 7th, post = 9th
    b = [10.0, 10.0, 10.0, 10.5, 10.5, 10.5]
    return pl.DataFrame({"date": D * 2, "symbol": ["A"] * 6 + ["NIFTYBEES"] * 6, "adj_close": a + b})


def test_reaction_and_when_it_is_usable():
    m = pl.DataFrame({"symbol": ["A"], "meeting": [date(2020, 1, 8)]})
    r = results.reactions(m, panel(), "NIFTYBEES")
    assert r["post"].item() == D[3]
    assert r["reaction"].item() == pytest.approx(0.10 - 0.05)
    s = results.signal_by_decision(r, m, [D[2], D[3]], 100)
    assert s[D[2]] == {} and s[D[3]]["A"] == pytest.approx(0.05)
    assert results.signal_by_decision(r, m, [D[5]], 4)[D[5]] == {}  # meeting more than 4 days before


def test_stale_data_refused():
    m = pl.DataFrame({"symbol": ["A"], "meeting": [date(2020, 1, 8)]})
    with pytest.raises(ValueError):
        results.signal_by_decision(results.reactions(m, panel(), "NIFTYBEES"), m, [date(2020, 3, 1)], 100)


def test_load_keeps_results_meetings(tmp_path):
    pl.DataFrame({"bm_symbol": ["A", "A", "B"], "bm_date": ["08-Jan-2020", "08-Jan-2020", "09-Jan-2020"],
                  "bm_purpose": ["Financial Results", "Results/Dividend", "Fund Raising"],
                  "bm_desc": ["x", "y", "raise funds"]}).write_parquet(tmp_path / "a.parquet")
    assert results.load(tmp_path).rows() == [("A", date(2020, 1, 8))]
