"""M125: NSE industry classification parser (src/mb/sources/nse_industry.py)."""
from pathlib import Path

import pytest

from mb.config.loader import load_industry_config
from mb.sources.nse_industry import parse_quote

ROOT = Path(__file__).resolve().parents[1]


def test_parse_quote_reads_the_four_levels_and_blanks_to_null():
    payload = {"equityResponse": [{"metaData": {"symbol": "20MICRONS", "isinCode": "INE144J01027"},
                                   "secInfo": {"macro": "Commodities", "sector": "Metals & Mining",
                                               "industryInfo": "Minerals & Mining", "basicIndustry": " "}}]}
    assert parse_quote(payload) == {"symbol": "20MICRONS", "isin": "INE144J01027", "macro": "Commodities",
                                    "sector": "Metals & Mining", "industry": "Minerals & Mining", "basic_industry": None}


def test_empty_response_fails():
    with pytest.raises(ValueError):
        parse_quote({"equityResponse": []})


def test_config_loads():
    assert load_industry_config(ROOT / "configs/data/nse_industry.yaml").raw_dir == "data/raw/nse_industry"


def test_weak_industry_names_bottom_half_by_mean_member_return():
    from datetime import date, timedelta

    import polars as pl

    from mb.strategy.momentum.params import IndustryFilter
    from mb.strategy.momentum.targets import weak_industry_names

    # returns over lookback 2 / skip 0 at the last date: A +100%, B +50% (industry X, mean 75%); C +10%, D 0% (Y, 5%);
    # E -50% (Z, one member: below min_members); F unclassified
    closes = {"A": [1, 2], "B": [2, 3], "C": [10, 11], "D": [5, 5], "E": [2, 1], "F": [1, 0.5]}
    rows = [{"date": date(2020, 1, 1) + timedelta(days=i), "symbol": s, "adj_close": 1.0}
            for s in closes for i in range(1)]
    rows += [{"date": date(2020, 1, 2) + timedelta(days=i), "symbol": s, "adj_close": float(c[i])}
             for s, c in closes.items() for i in range(2)]
    panel = pl.DataFrame(rows)
    cls = pl.DataFrame({"symbol": ["A", "B", "C", "D", "E"], "isin": [None] * 5, "macro": [None] * 5,
                        "sector": ["X", "X", "Y", "Y", "Z"], "industry": [None] * 5, "basic_industry": [None] * 5})
    f = IndustryFilter(raw_dir="", snapshot="", level="sector", lookback_sessions=1, skip_sessions=0, min_members=2,
                       drop_frac=0.5)
    d = date(2020, 1, 3)
    assert weak_industry_names(panel, cls, f, {d: list(closes)}) == {d: {"C": -1.0, "D": -1.0}}
