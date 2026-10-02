"""M103: a band on the regime filter (docs/research/m103.md)."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from mb.config.loader import load_strategy_config
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM103, RegimeM103
from mb.strategy.momentum.targets import banded, risk_on

ROOT = Path(__file__).resolve().parents[1]


def test_the_option_is_validated_routed_and_refused_by_paper():
    kw = dict(enabled=True, benchmark_symbol="JUNIORBEES", sma_sessions=200, risk_off_gross=0.5, risk_off_symbol="GOLDBEES",
              breadth_min_frac=None)
    with pytest.raises(ValidationError, match="single-benchmark"):
        RegimeM103(**kw, extra_benchmark_symbols=["NIFTYBEES"], band_frac=0.01)
    with pytest.raises(ValidationError, match="in \\(0, 0.5\\)"):
        RegimeM103(**kw, extra_benchmark_symbols=[], band_frac=0.0)
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m103_band1_r50g_jr_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM103
    with pytest.raises(ValueError, match="regime.band_frac"):
        check_supported(cfg.params)


def test_the_band_keeps_the_last_state_inside_it():
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(8)]
    # Average over 2 closes; ratios on days 1..7 against that average.
    closes = [100.0, 100.0, 99.8, 99.6, 96.0, 96.5, 97.2, 100.0]
    panel = pl.DataFrame({"date": days, "symbol": ["X"] * 8, "adj_close": closes})
    dates = days[1:]
    plain = risk_on(panel, "X", 2, dates)
    band = banded(panel, "X", 2, 0.01, dates)
    assert [plain[d] for d in dates] == [True, False, False, False, True, True, True]
    # Off only after a close more than 1% under the average (day 4), back on only more than 1% over (day 7).
    assert [band[d] for d in dates] == [True, True, True, False, False, False, True]
