"""M55: rank on the daytime or overnight part of the return (docs/research/m55.md)."""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError
from test_m5_momentum import _days, _frame
from test_m53_momentum import _m53

from mb.config.loader import load_strategy_config
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM55
from mb.strategy.momentum.targets import ranked

ROOT = Path(__file__).resolve().parents[1]


def _m55(part: str, **ranking) -> ParamsM55:
    p = _m53(None, frac=None).model_dump()
    p["ranking"] |= {"return_part": part} | ranking
    return ParamsM55.model_validate(p)


def test_each_part_ranks_by_its_own_return():
    # A gains 1.0% a day overnight only (opens at its close), B 0.9% a day in the daytime only (opens at the last close).
    days = _days(30)
    a = [100.0 * 1.010 ** i for i in range(30)]
    b = [100.0 * 1.009 ** i for i in range(30)]
    panel = _frame({"A": a, "B": b, "C": [100.0] * 30}, days)
    panel = panel.with_columns(pl.when(pl.col("symbol") == "B").then(pl.col("adj_close").shift(1).over("symbol"))
                               .otherwise(pl.col("adj_open")).alias("adj_open")).filter(pl.col("adj_open").is_not_null())
    d = days[-1]
    got = {part: ranked(panel, (p := _m55(part)).universe, p.ranking, d, d)[d] for part in ("total", "intraday", "overnight")}
    assert got["total"] == ["A", "B", "C"]
    assert got["intraday"] == ["B", "A", "C"]  # A and C have no daytime return: tie, by symbol
    assert got["overnight"] == ["A", "B", "C"]


def test_the_option_is_validated_routed_and_refused_by_paper():
    with pytest.raises(ValidationError, match="return_part intraday"):
        _m55("intraday", second_lookback_sessions=5)
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m55_intraday_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM55
    with pytest.raises(ValueError, match="ranking.return_part"):
        check_supported(cfg.params)
    check_supported(load_strategy_config(ROOT / "strategies/momentum/configs/m55_control_b2.yaml", ROOT).params)
