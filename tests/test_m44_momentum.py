"""M44: a name whose lookback window holds a trading gap is not eligible."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError
from test_m5_momentum import _days, _frame
from test_m40_momentum import _m40

from mb.config.loader import load_strategy_config
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM40, ParamsM44
from mb.strategy.momentum.targets import ranked

ROOT = Path(__file__).resolve().parents[1]


def _m44(gap: int | None) -> ParamsM44:
    p = _m40(None).model_dump()
    p["universe"] |= {"max_gap_days": gap}
    return ParamsM44.model_validate(p)


def _panel() -> tuple[pl.DataFrame, list]:
    # A rises fastest, then B, C. A's first 25 bars are moved 60 days earlier: a two-month gap inside its window.
    days = _days(30)
    panel = _frame({s: [100.0 * g ** i for i in range(30)] for s, g in {"A": 1.010, "B": 1.008, "C": 1.006}.items()}, days)
    early = (pl.col("symbol") == "A") & (pl.col("date") <= days[24])
    return panel.with_columns(pl.when(early).then(pl.col("date") - timedelta(days=60)).otherwise(pl.col("date")).alias("date")), days


def test_a_gap_inside_the_window_makes_a_name_ineligible():
    panel, days = _panel()
    d = days[-1]  # lookback 10 rows: A's gap (at its 26th row) is inside the window
    on, off = _m44(30), _m44(None)
    assert ranked(panel, on.universe, on.ranking, d, d)[d] == ["B", "C"]
    assert ranked(panel, off.universe, off.ranking, d, d)[d] == ["A", "B", "C"]
    assert ranked(panel, _m44(90).universe, on.ranking, d, d)[d] == ["A", "B", "C"]  # 60 days is within a 90-day limit


def test_the_gap_leaves_the_window_after_lookback_rows():
    panel, days = _panel()
    panel = pl.concat([panel, _frame({s: [200.0] * 10 for s in "ABC"}, _days(40)[30:])]).sort("symbol", "date")
    later = _days(40)[-1]  # 14 rows after A's gap, it is outside a 10-row window
    p = _m44(30)
    assert "A" in ranked(panel, p.universe, p.ranking, later, later)[later]


def test_option_is_validated_routed_and_accepted_by_paper():
    with pytest.raises(ValidationError, match="max_gap_days"):
        _m44(0)
    check_supported(_m44(30))
    pin = load_strategy_config(ROOT / "strategies/momentum/configs/m40_deliv40_gold20_b2.yaml", ROOT)
    assert type(pin.params) is ParamsM40
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m44_gap30_deliv40_gold20_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM44 and cfg.params.universe.max_gap_days == 30
