"""M5: rebalance simulator, momentum targets (buffer, regime, vol-adjusted rank, stocks only), the gate, and blends."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
from test_m3_sepa import _cfg, _market, _panel

from mb.config.loader import ConfigError, load_strategy_config
from mb.engine.gate import trades_touching_jumps
from mb.engine.rebalance import Target, simulate_targets
from mb.evaluation import baselines
from mb.runs.record import RunResult
from mb.strategy.blend.params import Params as BlendParams
from mb.strategy.blend.run import load_sleeves, mix
from mb.strategy.momentum.params import Params, Portfolio
from mb.strategy.momentum.targets import ranked, targets

ROOT = Path(__file__).resolve().parents[1]


def _days(n: int) -> list[date]:
    out, d = [], date(2020, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _bars(prices: dict[str, list[float]], days: list[date]) -> pl.DataFrame:
    return pl.DataFrame([(d, s, p, p) for s, ps in prices.items() for d, p in zip(days, ps)],
                        schema=["date", "symbol", "open", "close"], orient="row")


def _params(**over) -> Params:
    p = {"universe": {"allowed_series": ["EQ"], "min_price_inr": 10.0, "min_adv_inr": 1.0, "adv_window_sessions": 5,
                      "exclude_fund_units": False},
         "ranking": {"lookback_sessions": 20, "skip_sessions": 5, "score": "return"},
         "portfolio": {"top_n": 1, "hold_rank_max": 1},
         "regime": {"enabled": False, "benchmark_symbol": "IDX", "sma_sessions": 20, "risk_off_gross": 0.0},
         "initial_capital": 100000.0}
    for k, v in over.items():
        p[k] = p[k] | v
    return Params.model_validate(p)


def _frame(series: dict[str, list[float]], days: list[date], isin: dict[str, str] | None = None) -> pl.DataFrame:
    rows = [(d, s, (isin or {}).get(s, f"isin:INE{s}"), "EQ", p, 1e9, p, p)
            for s, ps in series.items() for d, p in zip(days, ps)]
    return pl.DataFrame(rows, schema=["date", "symbol", "security_id", "series", "close", "turnover", "adj_open", "adj_close"],
                        orient="row")


# --- rebalance simulator --------------------------------------------------------------------------------------------

def test_rebalance_trades_next_open_sells_first_and_equal_weights():
    days = _days(4)
    bars = _bars({"A": [100.0, 100.0, 110.0, 110.0], "B": [50.0, 50.0, 50.0, 50.0], "C": [20.0, 20.0, 20.0, 20.0]}, days)
    tg = {days[0]: Target({"A": 1.0, "B": 1.0}, 1.0), days[2]: Target({"B": 1.0, "C": 1.0}, 1.0)}
    res = simulate_targets(tg, bars, days, _market(False), 1000.0)
    assert res.equity["equity"].to_list() == pytest.approx([1000.0, 1000.0, 1050.0, 1050.0])
    last = res.fills.filter(pl.col("date") == days[3])
    assert last["side"].to_list()[0] == "sell" and last["symbol"].to_list()[0] == "A"
    assert last.filter(pl.col("side") == "buy")["symbol"].to_list() == ["B", "C"]  # B is topped up from 500 to its 525 goal
    assert res.holdings.filter(pl.col("symbol") == "A")["pnl"].item() == pytest.approx(50.0)
    assert res.rebalances == 2


def test_rebalance_scales_buys_to_cash_and_keeps_gross_cash():
    days = _days(3)
    bars = _bars({"A": [100.0] * 3}, days)
    res = simulate_targets({days[0]: Target({"A": 1.0}, 0.5)}, bars, days, _market(True), 1000.0)
    row = res.equity.row(1, named=True)
    assert row["cash"] == pytest.approx(1000.0 - 500.0 * 1.001 * 1.001)  # half invested, slippage and charges on top
    res = simulate_targets({days[0]: Target({"A": 1.0}, 1.0)}, bars, days, _market(True), 1000.0)
    assert res.equity["cash"][1] == pytest.approx(0.0, abs=1e-9)  # costs make the goal unaffordable, buys are scaled


def test_a_name_with_no_open_is_not_bought():
    days = _days(3)
    bars = _bars({"A": [100.0] * 3}, days).filter(~((pl.col("symbol") == "A") & (pl.col("date") == days[1])))
    res = simulate_targets({days[0]: Target({"A": 1.0}, 1.0)}, bars, days, _market(False), 1000.0)
    assert res.fills.is_empty() and res.equity["cash"].to_list() == [1000.0] * 3


# --- momentum targets -----------------------------------------------------------------------------------------------

def test_buffer_keeps_a_held_name_ranked_within_hold_rank_max():
    days = _days(90)
    # A leads early, then B overtakes; A stays second
    a = [100.0 * 1.004 ** i for i in range(90)]
    b = [100.0 * (1.001 ** i if i < 45 else 1.001 ** 45 * 1.02 ** (i - 45)) for i in range(90)]
    c = [100.0] * 90
    panel = _frame({"A": a, "B": b, "C": c}, days)
    plain = targets(panel, _params(), days[30], days[-1])
    buffered = targets(panel, _params(portfolio={"top_n": 1, "hold_rank_max": 2}), days[30], days[-1])
    assert list(plain[max(plain)].weights) == ["B"]
    assert list(buffered[max(buffered)].weights) == ["A"]


def test_hold_rank_max_below_top_n_is_refused():
    with pytest.raises(ValueError, match="hold_rank_max"):
        Portfolio(top_n=5, hold_rank_max=4)


def test_regime_goes_to_cash_below_the_benchmark_average():
    days = _days(90)
    idx = [100.0 * 1.002 ** i if i < 60 else 100.0 * 1.002 ** 60 * 0.97 ** (i - 60) for i in range(90)]
    panel = _frame({"A": [100.0 * 1.004 ** i for i in range(90)], "IDX": idx}, days)
    on = _params(regime={"enabled": True, "benchmark_symbol": "IDX", "sma_sessions": 20, "risk_off_gross": 0.0})
    tg = targets(panel, on, days[30], days[-1])
    gross = [tg[d].gross for d in sorted(tg)]
    assert gross[0] == 1.0 and gross[-1] == 0.0
    res = simulate_targets(tg, panel.select("date", "symbol", pl.col("adj_open").alias("open"), pl.col("adj_close").alias("close")),
                           days, _market(False), 100000.0)
    assert res.equity["open_positions"][-1] == 0


def test_return_over_vol_prefers_the_smoother_stock():
    days = _days(60)
    smooth = [100.0 * 1.002 ** i for i in range(60)]
    jumpy = [100.0 * 1.0025 ** i * (1.05 if i % 2 else 0.95) for i in range(60)]
    panel = _frame({"SMOOTH": smooth, "JUMPY": jumpy}, days)
    p = _params(ranking={"lookback_sessions": 25})  # an even 20-session span, so the zig-zag cancels out of the return
    by_return = ranked(panel, p.universe, p.ranking, days[30], days[-1])
    by_ratio = ranked(panel, p.universe, p.ranking.model_copy(update={"score": "return_over_vol"}), days[30], days[-1])
    d = max(by_return)
    assert by_return[d][0] == "JUMPY" and by_ratio[d][0] == "SMOOTH"


def test_exclude_fund_units_drops_inf_isins():
    days = _days(40)
    panel = _frame({"ETF": [100.0 * 1.01 ** i for i in range(40)], "STOCK": [100.0 * 1.001 ** i for i in range(40)]}, days,
                   isin={"ETF": "isin:INF000X01"})
    p = _params()
    got = ranked(panel, p.universe.model_copy(update={"exclude_fund_units": True}), p.ranking, days[25], days[-1])
    assert all(order == ["STOCK"] for order in got.values())
    assert ranked(panel, p.universe, p.ranking, days[25], days[-1])[max(got)][0] == "ETF"


def test_strategy_with_baseline_settings_equals_the_momentum_baseline(tmp_path):
    days = _panel(tmp_path / "p.parquet", {"UP": 0.004, "FLAT": 0.0, "DOWN": -0.002})
    curve, _ = baselines.momentum_curve(_cfg("x"), _market(True), tmp_path / "p.parquet", days[0], days[-1])
    panel = pl.read_parquet(tmp_path / "p.parquet")
    bars = panel.select("date", "symbol", pl.col("adj_open").alias("open"), pl.col("adj_close").alias("close"))
    mine = simulate_targets(targets(panel, _params(), days[0], days[-1]), bars, days, _market(True), 100000.0)
    assert mine.equity["equity"].to_list() == curve["equity"].to_list()


def test_gate_sees_a_holding_across_a_jump():
    days = _days(4)
    res = simulate_targets({days[0]: Target({"A": 1.0}, 1.0)}, _bars({"A": [100.0] * 4}, days), days, _market(False), 1000.0)
    jumps = pl.DataFrame({"symbol": ["A"], "date": [days[2]], "ratio": [0.5]})
    assert trades_touching_jumps(res.holdings, jumps).height == 1


# --- blend ----------------------------------------------------------------------------------------------------------

def _run(eq: list[float], days: list[date], sym: str) -> RunResult:
    equity = pl.DataFrame({"date": days, "equity": eq, "cash": [0.0] * len(eq), "invested_value": eq, "open_positions": [1] * len(eq)})
    trades = pl.DataFrame({"symbol": [sym], "entry_date": [days[0]], "exit_date": [days[-1]], "shares": [10.0], "pnl": [eq[-1] - eq[0]]})
    return RunResult(metrics={}, trades=trades, equity=equity)


def test_mix_weights_each_sleeve_by_its_starting_equity():
    days = _days(3)
    blend, trades, scales = mix([("a", 0.25, _run([100.0, 110.0, 120.0], days, "X")),
                                 ("b", 0.75, _run([50.0, 50.0, 25.0], days, "Y"))], 1000.0)
    assert blend["equity"].to_list() == pytest.approx([1000.0, 250 * 1.1 + 750, 250 * 1.2 + 375])
    assert scales == pytest.approx([2.5, 15.0])
    assert trades.filter(pl.col("sleeve") == "b")["pnl"].item() == pytest.approx(-25.0 * 15.0)
    with pytest.raises(ValueError, match="calendars"):
        mix([("a", 0.5, _run([1.0, 1.0, 1.0], days, "X")), ("b", 0.5, _run([1.0, 1.0], days[:2], "Y"))], 1.0)


def test_blend_refuses_a_sleeve_whose_config_changed():
    cfg = load_strategy_config(ROOT / "strategies/blend/configs/sepa_momentum_dev.yaml", ROOT)
    load_sleeves(cfg, ROOT)
    p = cfg.params
    assert isinstance(p, BlendParams)
    bad = p.model_copy(update={"sleeves": [p.sleeves[0].model_copy(update={"config_hash": "0" * 64}), p.sleeves[1]]})
    with pytest.raises(ConfigError, match="differs from the pinned"):
        load_sleeves(type(cfg)(cfg.strategy, bad, cfg.market, cfg.baselines, cfg.strategy_path), ROOT)


def test_blend_weights_must_sum_to_one():
    s = {"config": "x.yaml", "config_hash": "h"}
    with pytest.raises(ValueError, match="sum to 1"):
        BlendParams.model_validate({"sleeves": [s | {"weight": 0.5}, s | {"weight": 0.6}], "initial_capital": 1.0})
