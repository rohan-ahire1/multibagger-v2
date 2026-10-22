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
