"""M111: insider trades as a per-decision signal (src/mb/data/insider.py)."""
from datetime import date

import polars as pl
import pytest

from mb.data.insider import load, net_by_decision


def raw(tmp_path):
    rows = [  # date, symbol, person, category, mode, from, to, qty, value
        ("02-Jan-2020 18:00", "A", "P1", "Promoters", "Market Purchase", "01-Jan-2020", "01-Jan-2020", "10", "1000"),
        ("02-Jan-2020 18:05", "A", "P1", "Promoters", "Market Purchase", "01-Jan-2020", "01-Jan-2020", "10", "1000"),  # dup
        ("03-Jan-2020 10:00", "A", "E1", "Employees/Designated Employees", "Market Sale", "02-Jan-2020", "02-Jan-2020", "5", "500"),
        ("03-Jan-2020 10:00", "B", "D1", "Director", "Market Sale", "02-Jan-2020", "02-Jan-2020", "5", "700"),
        ("03-Jan-2020 10:00", "B", "D1", "Director", "ESOP", "02-Jan-2020", "02-Jan-2020", "5", "700"),
    ]
    df = pl.DataFrame(rows, schema=["date", "symbol", "acqName", "personCategory", "acqMode", "acqfromDt", "acqtoDt",
                                    "secAcq", "secVal"], orient="row")
    df.write_parquet(tmp_path / "x.parquet")
    return load(tmp_path, ["Promoters", "Director"])


def test_load_keeps_open_market_insiders_once(tmp_path):
    t = raw(tmp_path)
    assert sorted(t.rows()) == [("A", date(2020, 1, 3), 1000.0), ("B", date(2020, 1, 4), -700.0)]


def test_net_by_decision_window(tmp_path):
    t = raw(tmp_path)
    # first avail 2020-01-03: a window (d - L, d] is complete once it starts on or after that day
    net = net_by_decision(t, [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 4), date(2020, 1, 5)], 1)
    assert date(2020, 1, 2) not in net
    assert net[date(2020, 1, 3)] == {"A": 1000.0}
    assert net[date(2020, 1, 4)] == {"B": -700.0}
    assert net[date(2020, 1, 5)] == {}
    assert date(2020, 1, 4) not in net_by_decision(t, [date(2020, 1, 4)], 3)
    assert net_by_decision(t, [date(2020, 1, 5)], 3)[date(2020, 1, 5)] == {"A": 1000.0, "B": -700.0}
    with pytest.raises(ValueError):
        net_by_decision(t, [date(2020, 2, 1)], 1)


def test_load_xbrl_file_beside_old_drops_replaced_filings(tmp_path):
    raw(tmp_path)  # old-feed file x.parquet
    cols = ["date", "symbol", "acqName", "personCategory", "acqMode", "acqfromDt", "acqtoDt", "secAcq", "secVal",
            "appId", "prevAppId", "extra"]
    rows = [("06-May-2026 20:00", "C", "P2", "Promoters", "Market Purchase", "05-May-2026", "05-May-2026", "9", "900", "1", None, "x"),
            ("07-May-2026 20:00", "C", "P2", "Promoters", "Market Purchase", "05-May-2026", "05-May-2026", "9", "990", "2", "1", "x")]
    pl.DataFrame(rows, schema=cols, orient="row").write_parquet(tmp_path / "y.parquet")
    t = load(tmp_path, ["Promoters", "Director"])
    assert ("C", date(2026, 5, 8), 990.0) in t.rows() and len(t.filter(pl.col("symbol") == "C")) == 1
    assert t.height == 3
