"""M134: NSE SAST Reg 31 pledge events (src/mb/sources/nse_pledges.py) and the buy rule (targets.pledge_flags)."""
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from mb.config.loader import load_pledge_config
from mb.sources import nse_pledges
from mb.strategy.momentum.params import Pledges
from mb.strategy.momentum.targets import pledge_flags

ROOT = Path(__file__).resolve().parents[1]


def _row(**kw):
    base = {"symbol": "X", "broadcastdate": "29-Jan-2016 16:30:02", "eventDetailsType": "Creation",
            "eventDetailsTypeEncumb": "Pledge", "eventDetailsPerc": "0.03", "seqId": "1"}
    return {**base, **kw}


def test_months_inclusive_across_years():
    assert nse_pledges.months("2013-11", "2014-02") == ["2013-11", "2013-12", "2014-01", "2014-02"]


def test_parse_keeps_fields_as_strings_and_fails_without_data():
    df = nse_pledges.parse({"data": [_row(eventDetailsPerc=0.5)]})
    assert df.height == 1 and df["eventDetailsPerc"][0] == "0.5" and df["promoterName"][0] is None
    assert set(df.columns) == set(nse_pledges.FIELDS)
    with pytest.raises(ValueError):
        nse_pledges.parse({})


def test_load_lags_a_day_lowercases_and_dedups(tmp_path):
    rows = [_row(), _row(), _row(seqId="2", eventDetailsType="Invocation", broadcastdate="31-JAN-2016 09:00:00",
                                 eventDetailsPerc=" ")]
    nse_pledges.parse({"data": rows}).write_parquet(tmp_path / "2016-01.parquet")
    x = nse_pledges.load(tmp_path)
    assert x.rows() == [("X", date(2016, 1, 30), "creation", "pledge", 0.03),
                        ("X", date(2016, 2, 1), "invocation", "pledge", None)]


def test_load_missing_folder_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        nse_pledges.load(tmp_path)


def test_pledge_flags_kind_size_window():
    ev = pl.DataFrame({"symbol": ["A", "A", "B", "C", "D"],
                       "avail": [date(2020, 1, 1), date(2020, 3, 1), date(2020, 3, 1), date(2020, 3, 1), date(2020, 3, 2)],
                       "kind": ["creation", "creation", "release", "invocation", "creation"],
                       "encumbrance": ["pledge"] * 5, "pct": [1.0, 1.0, 1.0, None, 1.0]})
    pg = Pledges(raw_dir="", kinds=["creation", "invocation"], min_pct=0.0, lookback_days=30, drop_held=False)
    d = date(2020, 3, 1)
    # A: one event in the window (the January one is older than 30 days); B: release not counted; C: no size counts as
    # 0 >= 0; D: broadcast after the decision
    assert pledge_flags(ev, pg, [date(2020, 1, 15), d]) == {d: {"A": -1.0, "C": -1.0}}
    big = pg.model_copy(update={"min_pct": 0.5})
    assert pledge_flags(ev, big, [d]) == {d: {"A": -1.0}}


def test_config_loads():
    assert load_pledge_config(ROOT / "configs/data/nse_pledges.yaml").raw_dir == "data/raw/nse_pledges"
