"""M10: 52-week-high, residual momentum and frog-in-the-pan ranking options, and config routing."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from test_m5_momentum import _days, _frame, _params

from mb.config.loader import load_strategy_config
from mb.live.paper import check_supported
from mb.strategy.momentum.params import ParamsM8, ParamsM10
from mb.strategy.momentum.targets import _residual_score, ranked, targets

ROOT = Path(__file__).resolve().parents[1]


def _m10(**over) -> ParamsM10:
    p = _params().model_dump()
    p["ranking"] |= {"second_lookback_sessions": None, "high_window_sessions": None, "residual_beta_sessions": None,
                     "residual_benchmark_symbol": "IDX", "frog_candidates_per_slot": None}
    p["portfolio"] |= {"resize_held": True, "max_per_sector": None}
    p["sizing"] = {"vol_target_annual": None, "vol_benchmark_symbol": "IDX", "vol_window_sessions": 10}
    for k, v in over.items():
        p[k] = p[k] | v
    return ParamsM10.model_validate(p)


def _wiggle(n: int, seed: int) -> list[float]:
    """Deterministic daily returns with enough spread to estimate a beta."""
    return [0.01 * math.sin(1.7 * i + seed) + 0.004 * math.cos(0.9 * i * (seed + 1)) for i in range(n)]


def _prices(rets: list[float]) -> list[float]:
    out = [100.0]
    for r in rets[1:]:
        out.append(out[-1] * math.exp(r))
    return out


# --- configs --------------------------------------------------------------------------------------------------------

def test_m8_configs_keep_their_model_and_m10_configs_route_to_m10():
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m8_top40_stocks_dev_e.yaml", ROOT).params) is ParamsM8
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m10_control_b1.yaml", ROOT).params) is ParamsM10


def test_two_score_options_at_once_are_refused():
    with pytest.raises(ValueError, match="at most one"):
        _m10(ranking={"high_window_sessions": 10, "residual_beta_sessions": 30})


def test_paper_trading_refuses_m10_options_but_not_the_control():
    check_supported(_m10())
    for opt in ({"high_window_sessions": 10}, {"residual_beta_sessions": 30}, {"frog_candidates_per_slot": 2.0}):
        with pytest.raises(ValueError, match="M10"):
            check_supported(_m10(ranking=opt))


# --- ranking --------------------------------------------------------------------------------------------------------

def test_m10_with_every_option_off_equals_the_plain_strategy():
    days = _days(90)
    panel = _frame({"A": _prices(_wiggle(90, 1)), "B": _prices(_wiggle(90, 2)), "C": _prices(_wiggle(90, 3)),
                    "IDX": _prices(_wiggle(90, 4))}, days)
    port = {"top_n": 2, "hold_rank_max": 2}
    assert targets(panel, _params(portfolio=port), days[30], days[-1]) == targets(panel, _m10(portfolio=port), days[30], days[-1])


def test_high_window_orders_by_nearness_to_the_high_and_breaks_ties_by_the_score():
    days = _days(60)
    # FAR rose most but has fallen 20% from its high; NEAR_SLOW and NEAR_FAST both close at their high.
    far = [100.0 * 1.02 ** i for i in range(50)] + [100.0 * 1.02 ** 49 * 0.978 ** (i - 49) for i in range(50, 60)]
    panel = _frame({"FAR": far, "NEAR_SLOW": [100.0 * 1.002 ** i for i in range(60)],
                    "NEAR_FAST": [100.0 * 1.005 ** i for i in range(60)]}, days)
    panel = panel.with_columns(pl.col("adj_close").alias("adj_high"))
    p = _m10(ranking={"high_window_sessions": 30})
    got = ranked(panel, p.universe, p.ranking, days[-1], days[-1], 1)[days[-1]]
    assert got == ["NEAR_FAST", "NEAR_SLOW", "FAR"]
    plain = ranked(panel, p.universe, _m10().ranking, days[-1], days[-1], 1)[days[-1]]
    assert plain[0] == "FAR"


def test_residual_score_matches_a_direct_least_squares_fit():
    n_days, big, lookback, skip = 80, 40, 20, 5
    days = _days(n_days)
    m = _wiggle(n_days, 4)
    y = [0.8 * a + e for a, e in zip(m, _wiggle(n_days, 7))]
    panel = _frame({"S": _prices(y), "IDX": _prices(m)}, days)
    p = _m10(ranking={"lookback_sessions": lookback, "skip_sessions": skip, "residual_beta_sessions": big})
    got = (panel.filter(pl.col("symbol") == "S").sort("date")
           .with_columns((pl.col("adj_close") / pl.col("adj_close").shift(1)).log().alias("_ret"),
                         pl.Series("_bench_ret", [None] + list(np.diff(np.log(_prices(m))))))
           .with_columns(_residual_score(p.ranking).alias("r"))["r"].to_list())
    t = n_days - 1
    ys, xs = np.log(_prices(y)), np.log(_prices(m))
    ry, rx = np.diff(ys), np.diff(xs)  # ry[k] is the return into row k + 1
    end = t - skip  # last row inside both windows
    fit_y, fit_x = ry[end - big:end], rx[end - big:end]
    beta, alpha = np.polyfit(fit_x, fit_y, 1)
    n = lookback - skip
    e = ry[end - n:end] - alpha - beta * rx[end - n:end]
    assert got[t] == pytest.approx(e.sum() / e.std(ddof=1), rel=1e-9)


def test_residual_prefers_the_stock_specific_gain_over_market_beta():
    days = _days(90)
    m = [r + 0.003 for r in _wiggle(90, 4)]  # a rising market
    panel = _frame({"IDX": _prices(m),
                    "BETA": _prices([2.0 * r + 0.3 * e for r, e in zip(m, _wiggle(90, 5))]),        # twice the market
                    "ALPHA": _prices([0.5 * a + 0.002 + 0.3 * e for a, e in zip(m, _wiggle(90, 9))])}, days)
    base = {"lookback_sessions": 20, "skip_sessions": 5}
    plain = _m10(ranking=base)
    resid = _m10(ranking=base | {"residual_beta_sessions": 40})
    d = days[-1]
    assert ranked(panel, plain.universe, plain.ranking, d, d, 1)[d][0] == "BETA"
    got = ranked(panel, resid.universe, resid.ranking, d, d, 1)[d]
    assert got.index("ALPHA") < got.index("BETA")  # IDX itself fits exactly: no residual spread, so not ranked


def test_frog_reorders_the_top_candidates_by_information_discreteness():
    days = _days(40)
    # Over the 15-session span both gain about 10%. SMOOTH: small gains every day. JUMPY: one +16% day, small losses
    # on the others. LAG rises least: with 1 slot the candidates are the top 2, so LAG stays last.
    smooth = [100.0 * 1.0064 ** i for i in range(40)]
    jumpy = [100.0 * (0.997 ** i) * (1.16 if i >= 30 else 1.0) for i in range(40)]
    lag = [100.0 * 1.001 ** i for i in range(40)]
    panel = _frame({"SMOOTH": smooth, "JUMPY": jumpy, "LAG": lag}, days)
    base = {"lookback_sessions": 20, "skip_sessions": 5}
    plain = _m10(ranking=base)
    frog = _m10(ranking=base | {"frog_candidates_per_slot": 2.0})
    d = days[-1]
    before = ranked(panel, plain.universe, plain.ranking, d, d, 1)[d]
    after = ranked(panel, frog.universe, frog.ranking, d, d, 1)[d]
    assert before == ["JUMPY", "SMOOTH", "LAG"]
    assert after == ["SMOOTH", "JUMPY", "LAG"]
