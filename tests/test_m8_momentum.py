"""M8: momentum options (second lookback, no resizing of held names, sector cap, volatility target) and config routing."""
from __future__ import annotations

import math
from pathlib import Path

import polars as pl
import pytest
import yaml
from test_m3_sepa import _market
from test_m5_momentum import _bars, _days, _frame, _params

from mb.config.loader import ConfigError, load_paper_config, load_strategy_config
from mb.engine.rebalance import Target, simulate_targets
from mb.strategy.momentum.params import Params, ParamsM8
from mb.strategy.momentum.targets import ranked, targets

ROOT = Path(__file__).resolve().parents[1]


def _m8(**over) -> ParamsM8:
    p = _params().model_dump()
    p["ranking"] |= {"second_lookback_sessions": None}
    p["portfolio"] |= {"resize_held": True, "max_per_sector": None}
    p["sizing"] = {"vol_target_annual": None, "vol_benchmark_symbol": "IDX", "vol_window_sessions": 10}
    for k, v in over.items():
        p[k] = p[k] | v
    return ParamsM8.model_validate(p)


def _up(rate: float, n: int) -> list[float]:
    return [100.0 * (1 + rate) ** i for i in range(n)]


# --- configs --------------------------------------------------------------------------------------------------------

def test_pre_m8_configs_keep_their_model_and_hash():
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/voladj_dev.yaml", ROOT).params) is Params
    load_paper_config(ROOT / "configs/paper/momentum_voladj.yaml", ROOT)  # refuses a changed hash
    assert type(load_strategy_config(ROOT / "strategies/momentum/configs/m8_control_dev.yaml", ROOT).params) is ParamsM8


def test_a_config_with_some_m8_keys_is_refused(tmp_path):
    raw = yaml.safe_load((ROOT / "strategies/momentum/configs/m8_control_dev.yaml").read_text())
    del raw["params"]["sizing"]
    (tmp_path / "c.yaml").write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError):
        load_strategy_config(tmp_path / "c.yaml", ROOT)


# --- targets --------------------------------------------------------------------------------------------------------

def test_m8_with_every_option_off_equals_the_plain_strategy():
    days = _days(90)
    panel = _frame({"A": _up(0.004, 90), "B": [100.0 * (1.001 ** i if i < 45 else 1.001 ** 45 * 1.02 ** (i - 45)) for i in range(90)],
                    "C": _up(0.002, 90), "IDX": _up(0.001, 90)}, days)
    port = {"top_n": 2, "hold_rank_max": 2}
    assert (targets(panel, _params(portfolio=port), days[30], days[-1])
            == targets(panel, _m8(portfolio=port), days[30], days[-1], sectors={}, days_per_year=252))


def test_second_lookback_orders_by_the_mean_percentile_rank():
    days = _days(80)
    series = {s: [100.0 * (1 + 0.002 * k) ** i * (1 + 0.05 * math.sin(i / (3 + k))) for i in range(80)]
              for k, s in enumerate(["A", "B", "C", "D", "E", "F"])}
    panel = _frame(series, days)
    p = _m8(ranking={"second_lookback_sessions": 12})
    long = ranked(panel, p.universe, _params().ranking, days[30], days[-1])
    short = ranked(panel, p.universe, _params(ranking={"lookback_sessions": 12}).ranking, days[30], days[-1])
    got = ranked(panel, p.universe, p.ranking, days[30], days[-1])
    assert any(long[d] != short[d] for d in got)
    for d, order in got.items():
        n = len(order)
        total = {s: (n - long[d].index(s)) + (n - short[d].index(s)) for s in order}
        assert order == sorted(order, key=lambda s: (-total[s], s))


def test_sector_cap_skips_names_from_a_full_industry_and_leaves_unmapped_names_uncapped():
    days = _days(60)
    panel = _frame({"A": _up(0.004, 60), "B": _up(0.003, 60), "C": _up(0.002, 60), "D": _up(0.001, 60)}, days)
    p = _m8(portfolio={"top_n": 3, "hold_rank_max": 3, "max_per_sector": 1})
    tg = targets(panel, p, days[30], days[-1], sectors={"A": "X", "B": "X"})
    assert all(list(t.weights) == ["A", "C", "D"] for t in tg.values())
    with pytest.raises(ValueError, match="sector map"):
        targets(panel, p, days[30], days[-1])


def test_no_resize_marks_kept_names_and_the_engine_leaves_them_alone():
    days = _days(60)
    panel = _frame({"A": _up(0.004, 60), "B": _up(0.003, 60), "C": _up(0.001, 60)}, days)
    tg = targets(panel, _m8(portfolio={"top_n": 2, "hold_rank_max": 2, "resize_held": False}), days[30], days[-1], sectors={})
    first, *rest = sorted(tg)
    assert tg[first].keep_size == frozenset() and all(tg[d].keep_size == {"A", "B"} for d in rest)

    d4 = _days(4)
    bars = _bars({"A": [100.0, 100.0, 200.0, 200.0], "B": [100.0] * 4}, d4)
    resize = {d4[0]: Target({"A": 1.0, "B": 1.0}, 1.0), d4[2]: Target({"A": 1.0, "B": 1.0}, 1.0)}
    keep = {d4[0]: resize[d4[0]], d4[2]: Target({"A": 1.0, "B": 1.0}, 1.0, frozenset({"A", "B"}))}
    assert simulate_targets(resize, bars, d4, _market(False), 1000.0).fills.filter(pl.col("date") == d4[3]).height == 2
    assert simulate_targets(keep, bars, d4, _market(False), 1000.0).fills.filter(pl.col("date") == d4[3]).is_empty()


def test_volatility_target_scales_gross_by_benchmark_volatility():
    days = _days(60)
    idx = [100.0 if i % 2 == 0 else 102.0 for i in range(60)]  # log returns alternate +-log(1.02); a 10-session window has mean 0
    panel = _frame({"A": _up(0.004, 60), "IDX": idx}, days)
    vol = math.log(1.02) * math.sqrt(10 / 9) * math.sqrt(252)
    tg = targets(panel, _m8(sizing={"vol_target_annual": 0.1}), days[30], days[-1], sectors={}, days_per_year=252)
    assert all(t.gross == pytest.approx(0.1 / vol) for t in tg.values())
    tg = targets(panel, _m8(sizing={"vol_target_annual": 1.0}), days[30], days[-1], sectors={}, days_per_year=252)
    assert all(t.gross == 1.0 for t in tg.values())
    with pytest.raises(ValueError, match="days_per_year"):
        targets(panel, _m8(sizing={"vol_target_annual": 0.1}), days[30], days[-1], sectors={})
