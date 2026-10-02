"""M53: drop the names whose recent delivered volume is lowest against their own past (docs/research/m53.md)."""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError
from test_m40_momentum import _m40, _panel

from mb.config.loader import load_strategy_config
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM53
from mb.strategy.momentum.targets import ranked

ROOT = Path(__file__).resolve().parents[1]


def _m53(drop: float | None, frac: float | None = 0.2) -> ParamsM53:
    p = _m40(frac).model_dump()
    abd = None if drop is None else {"recent_sessions": 5, "base_sessions": 10, "drop_frac": drop}
    p["universe"] |= {"max_gap_days": None, "abnormal_delivery": abd}
    return ParamsM53.model_validate(p)


def test_the_lowest_recent_delivery_ratio_is_dropped_after_the_share_filter():
    panel, days = _panel({"A": 0.2, "B": 0.6, "C": 0.5, "D": 0.4, "E": 0.45})
    # C's delivered volume doubles over the last 5 sessions, D's halves: D has the lowest ratio among B-E.
    last5 = pl.col("date").is_in(days[-5:])
    panel = panel.with_columns(pl.when(last5 & (pl.col("symbol") == "C")).then(pl.col("deliv_qty") * 2)
                               .when(last5 & (pl.col("symbol") == "D")).then(pl.col("deliv_qty") // 2)
                               .otherwise(pl.col("deliv_qty")).alias("deliv_qty"))
    d = days[-1]
    off = _m53(None)
    assert ranked(panel, off.universe, off.ranking, d, d)[d] == ["B", "C", "D", "E"]  # A goes on delivery share
    on = _m53(0.25)  # ceil(0.25 * 4) = 1 more: D
    assert ranked(panel, on.universe, on.ranking, d, d)[d] == ["B", "C", "E"]


def test_the_option_is_validated_routed_and_refused_by_paper():
    with pytest.raises(ValidationError, match="needs delivery_drop_frac"):
        _m53(0.25, frac=None)
    with pytest.raises(ValidationError, match="drop_frac"):
        _m53(1.0)
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m53_abd25_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM53
    with pytest.raises(ValueError, match="universe.abnormal_delivery"):
        check_supported(cfg.params)
    check_supported(load_strategy_config(ROOT / "strategies/momentum/configs/m53_control_b2.yaml", ROOT).params)
