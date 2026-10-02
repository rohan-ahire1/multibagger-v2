"""M97: a graded regime over several benchmarks (docs/research/m97.md)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from mb.config.loader import load_strategy_config
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM97, RegimeM97
from mb.strategy.momentum.run import simulate

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "strategies/momentum/configs"


def test_the_option_is_validated_routed_and_refused_by_paper():
    kw = dict(enabled=True, benchmark_symbol="NIFTYBEES", sma_sessions=200, risk_off_gross=0.5, risk_off_symbol="GOLDBEES")
    with pytest.raises(ValidationError, match="distinct"):
        RegimeM97(**kw, extra_benchmark_symbols=["NIFTYBEES"])
    with pytest.raises(ValidationError, match="needs the regime enabled"):
        RegimeM97(**{**kw, "enabled": False, "risk_off_symbol": None}, extra_benchmark_symbols=["JUNIORBEES"])
    cfg = load_strategy_config(CFG / "m97_r50g_nj_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM97
    with pytest.raises(ValueError, match="regime.extra_benchmark_symbols"):
        check_supported(cfg.params)


def test_without_extra_benchmarks_the_m89_run_is_unchanged():
    a = simulate(load_strategy_config(CFG / "m89_g0s10_r50g_b2.yaml", ROOT), ROOT)
    d = load_strategy_config(CFG / "m97_r50g_nj_b2.yaml", ROOT)
    p = d.params.model_copy(update={"regime": d.params.regime.model_copy(update={"extra_benchmark_symbols": []})})
    b = simulate(replace(d, params=p), ROOT)
    assert a.equity["equity"].to_list() == b.equity["equity"].to_list()


def test_graded_gross_lies_between_the_single_benchmark_books():
    """On each date the graded book's gold share is 0, 0.25 or 0.5, so its run differs from both one-benchmark runs."""
    g = simulate(load_strategy_config(CFG / "m97_r50g_nj_b2.yaml", ROOT), ROOT).equity["equity"].to_list()
    n = simulate(load_strategy_config(CFG / "m89_g0s10_r50g_b2.yaml", ROOT), ROOT).equity["equity"].to_list()
    j = simulate(load_strategy_config(CFG / "m95_r50g_jr_b2.yaml", ROOT), ROOT).equity["equity"].to_list()
    assert g != n and g != j
