"""M13: drop fund units by symbol, so a fund's rows from before its ISIN appears are dropped too; config routing."""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from test_m5_momentum import _days, _frame
from test_m12_momentum import _m12

from mb.config.loader import load_strategy_config
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM12, ParamsM13
from mb.strategy.momentum.targets import ranked, targets

ROOT = Path(__file__).resolve().parents[1]


def _m13(**over) -> ParamsM13:
    p = _m12().model_dump()
    p["universe"] |= {"exclude_fund_units": True, "fund_units_by_symbol": True}
    for k, v in over.items():
        p[k] = p[k] | v
    return ParamsM13.model_validate(p)


def _panel() -> tuple[pl.DataFrame, list]:
    """FUND rises fastest; its id is `fallback:` for the first 40 rows, then an INF ISIN."""
    days = _days(60)
    panel = _frame({"FUND": [100.0 * 1.01 ** i for i in range(60)], "A": [100.0 * 1.005 ** i for i in range(60)],
                    "B": [100.0 * 1.002 ** i for i in range(60)]}, days)
    late = pl.col("date") >= days[40]
    fund = pl.col("symbol") == "FUND"
    panel = panel.with_columns(pl.when(fund & late).then(pl.lit("isin:INF123")).when(fund).then(pl.lit("fallback:FUND:EQ"))
                               .otherwise(pl.col("security_id")).alias("security_id"))
    return panel, days


def test_m12_configs_keep_their_model_and_m13_configs_route_to_m13():
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m12_control_b1.yaml", ROOT).params) is ParamsM12
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m13_clean_invvol_b2.yaml", ROOT).params) is ParamsM13


def test_the_option_needs_exclude_fund_units():
    with pytest.raises(ValueError, match="needs exclude_fund_units"):
        _m13(universe={"exclude_fund_units": False})


def test_a_fund_with_a_fallback_id_is_dropped_only_by_symbol():
    panel, days = _panel()
    base = {"lookback_sessions": 20, "skip_sessions": 1}
    d = days[30]  # FUND still has its fallback id here
    by_id = _m13(universe={"fund_units_by_symbol": False}, ranking=base)
    by_symbol = _m13(ranking=base)
    assert ranked(panel, by_id.universe, by_id.ranking, d, d)[d] == ["FUND", "A", "B"]
    assert ranked(panel, by_symbol.universe, by_symbol.ranking, d, d)[d] == ["A", "B"]
    late = days[-1]
    assert ranked(panel, by_id.universe, by_id.ranking, late, late)[late] == ["A", "B"]


def test_off_equals_m12_and_paper_accepts_the_option():
    panel, days = _panel()
    base = {"lookback_sessions": 20, "skip_sessions": 1}
    off = _m13(universe={"fund_units_by_symbol": False}, ranking=base)
    m12 = _m12(universe={"exclude_fund_units": True}, ranking=base)
    assert targets(panel, off, days[25], days[-1]) == targets(panel, m12, days[25], days[-1])
    check_supported(_m13())
