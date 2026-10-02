"""M99: the regime on market breadth (docs/research/m99.md)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from mb.config.loader import load_strategy_config
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM99, RegimeM99
from mb.strategy.momentum.targets import breadth_on

ROOT = Path(__file__).resolve().parents[1]


def test_the_option_is_validated_routed_and_refused_by_paper():
    kw = dict(enabled=True, sma_sessions=200, risk_off_gross=0.5, risk_off_symbol="GOLDBEES", extra_benchmark_symbols=[])
    with pytest.raises(ValidationError, match="go together"):
        RegimeM99(**kw, benchmark_symbol="NIFTYBEES", breadth_min_frac=0.5)
    with pytest.raises(ValidationError, match="go together"):
        RegimeM99(**kw, benchmark_symbol="UNIVERSE", breadth_min_frac=None)
    with pytest.raises(ValidationError, match="in \\(0, 1\\)"):
        RegimeM99(**kw, benchmark_symbol="UNIVERSE", breadth_min_frac=1.0)
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m99_r50g_br_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM99
    with pytest.raises(ValueError, match="regime.breadth_min_frac"):
        check_supported(cfg.params)


def test_breadth_counts_only_eligible_stocks_with_a_full_average():
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m99_r50g_br_b2.yaml", ROOT)
    u = cfg.params.universe
    days = [date(2020, 1, d) for d in range(1, 6)]

    def rows(sym, closes, series="EQ", sid="isin:INE1"):
        return [{"date": d, "symbol": sym, "series": series, "security_id": sid, "close": c, "adj_close": c,
                 "turnover": 1e12} for d, c in zip(days, closes)]
    up, down = [100, 100, 100, 100, 110], [100, 100, 100, 100, 90]
    panel = pl.DataFrame(rows("A", up) + rows("B", down) + rows("C", down) + rows("F", up, sid="isin:INF1")
                         + rows("Z", up, series="BE"))
    small = u.model_copy(update={"adv_window_sessions": 1})
    # Of A, B, C (F is a fund, Z is not an allowed series) one in three is above: off at 0.5, on at 0.3.
    assert breadth_on(panel, small, 3, 0.5, [days[-1]], None) == {days[-1]: False}
    assert breadth_on(panel, small, 3, 0.3, [days[-1]], None) == {days[-1]: True}
    with pytest.raises(ValueError, match="no eligible stock"):
        breadth_on(panel, small, 10, 0.5, [days[-1]], None)
