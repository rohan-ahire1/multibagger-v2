"""M1 exit check on real data: the built panel equals v1's sim layer. Skipped where the data is absent."""
import json
from pathlib import Path

import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "data/datasets/nse_research/2026-09-29"
V1_SIM = Path.home() / "projects/Multibagger/data/adjusted/sim_total_return/ohlcv_all.parquet"

pytestmark = pytest.mark.skipif(not (DATASET.exists() and V1_SIM.exists()), reason="real data not present")


def test_panel_matches_v1_sim_layer():
    v2 = pl.read_parquet(DATASET / "panel.parquet")
    v1 = pl.read_parquet(V1_SIM)
    assert v2.height == v1.height
    j = v2.join(v1, on=["symbol", "date"], how="inner", suffix="_v1")
    assert j.height == v1.height
    for a, b in (("adj_open", "open_v1"), ("adj_high", "high_v1"), ("adj_low", "low_v1"),
                 ("adj_close", "close_v1"), ("adj_volume", "volume_v1")):
        assert (j[a] != j[b]).sum() == 0, a
    assert (j["close"] != j["raw_price"]).sum() == 0  # raw close is v1's raw_price


def test_reference_counts():
    m = json.loads((DATASET / "manifest.json").read_text())
    assert m["share_event_status"] == {"applied_small": 26, "duplicate": 2, "matched": 1340, "unmatched": 135}
    assert pl.read_parquet(DATASET / "unexplained_jumps.parquet").height == 1139
