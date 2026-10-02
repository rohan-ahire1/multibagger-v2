"""M89: the regime's risk-off share buys a symbol instead of staying in cash (docs/research/m89.md)."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from mb.config.loader import load_strategy_config
from mb.engine.rebalance import Target
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM89, RegimeM89
from mb.strategy.momentum.targets import with_risk_off

ROOT = Path(__file__).resolve().parents[1]


def test_the_uninvested_share_buys_the_symbol():
    t = with_risk_off(Target({"A": 1.0, "B": 3.0}, 0.5, frozenset({"A"})), "G")
    assert t.gross == 1.0 and t.keep_size == frozenset({"A"})
    assert t.weights == pytest.approx({"A": 0.125, "B": 0.375, "G": 0.5})
    assert with_risk_off(Target({}, 0.0), "G").weights == {"G": 1.0}
    # A fixed sleeve in the same symbol is added to, not replaced.
    assert with_risk_off(Target({"A": 0.75, "G": 0.25}, 0.5), "G").weights == pytest.approx({"A": 0.375, "G": 0.625})


def test_the_option_is_validated_and_routed_and_paper_refuses_only_the_stop():
    with pytest.raises(ValidationError, match="needs the regime enabled"):
        RegimeM89(enabled=False, benchmark_symbol="NIFTYBEES", sma_sessions=200, risk_off_gross=0.0,
                  risk_off_symbol="GOLDBEES")
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m89_g0s10_r50g_b2.yaml", ROOT)
    assert type(cfg.params) is ParamsM89
    with pytest.raises(ValueError, match="exits.stop_loss_frac") as e:  # M106: the gold switch itself is supported
        check_supported(cfg.params)
    assert "regime.risk_off_symbol" not in str(e.value)


def test_without_the_symbol_the_m88_run_is_unchanged():
    from dataclasses import replace

    from mb.strategy.momentum.run import simulate
    a = simulate(load_strategy_config(ROOT / "strategies/momentum/configs/m88_g0s10_r50_b2.yaml", ROOT), ROOT)
    d = load_strategy_config(ROOT / "strategies/momentum/configs/m89_g0s10_r50g_b2.yaml", ROOT)
    p = d.params.model_copy(update={"regime": d.params.regime.model_copy(update={"risk_off_symbol": None})})
    b = simulate(replace(d, params=p), ROOT)
    assert a.equity["equity"].to_list() == b.equity["equity"].to_list()
