"""M116: bulk and block deals loader (src/mb/data/deals.py)."""
from datetime import date

import polars as pl
import pytest

from mb.data import deals


def test_load_signs_values_dedups_and_lags(tmp_path):
    a, b = tmp_path / "bulk", tmp_path / "block"
    a.mkdir(), b.mkdir()
    row = {"BD_DT_DATE": "30-SEP-2026", "BD_SYMBOL": "X", "BD_CLIENT_NAME": "F", "BD_BUY_SELL": "BUY",
           "BD_QTY_TRD": 10.0, "BD_TP_WATP": 5.0}
    pl.DataFrame([row, row, {**row, "BD_BUY_SELL": "SELL", "BD_QTY_TRD": 4.0}]).write_parquet(a / "x.parquet")
    pl.DataFrame([{**row, "BD_DT_DATE": "01-Oct-2026"}]).write_parquet(b / "y.parquet")
    x = deals.load([a, b])
    assert x.sort("avail", "value").rows() == [("X", date(2026, 10, 1), -20.0), ("X", date(2026, 10, 1), 50.0),
                                               ("X", date(2026, 10, 2), 50.0)]


def test_missing_folder_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        deals.load([tmp_path])
