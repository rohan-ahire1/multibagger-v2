"""M3: contraction count, SEPA signal parity with v1, trade parity, and the baselines."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from mb.config.loader import load_strategy_config
from mb.config.models import Adoption, BaselinesConfig, BuyAndHold, MarketConfig, Momentum
from mb.engine.run import evaluate, load_bars
from mb.evaluation import baselines
from mb.evaluation.metrics import equity_metrics
from mb.strategy.sepa.contraction import count_contractions
from mb.strategy.sepa.run import make_signals

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "strategies/sepa/configs/v1_port.yaml"
PANEL = ROOT / "data/datasets/nse_research/2026-09-29/panel.parquet"
needs_panel = pytest.mark.skipif(not PANEL.exists(), reason="research dataset not built on this machine")


# --- contraction count ---------------------------------------------------------------------------------------------

def _zigzag(peaks: list[float]) -> np.ndarray:
    out = [0.0]
    for p in peaks:
        out += [p, 0.0]
    return np.array(out)


def test_shrinking_peaks_count_each_contraction():
    assert count_contractions(_zigzag([0.10, 0.08, 0.06, 0.04]), 1, 0.02) == 4


def test_a_wider_latest_peak_resets_the_count():
    assert count_contractions(_zigzag([0.04, 0.06, 0.08]), 1, 0.02) == 1


def test_only_the_run_ending_at_the_latest_peak_counts():
    assert count_contractions(_zigzag([0.03, 0.09, 0.07, 0.05]), 1, 0.02) == 3


def test_flat_or_short_series_has_no_contractions():
    assert count_contractions(np.full(30, 0.05), 3, 0.02) == 0
    assert count_contractions(np.array([0.1, 0.2]), 3, 0.02) == 0


def test_peaks_below_the_minimum_are_ignored():
    assert count_contractions(_zigzag([0.01, 0.008]), 1, 0.02) == 0


# --- SEPA parity with v1 (needs the research dataset) --------------------------------------------------------------

@pytest.fixture(scope="module")
def cfg():
    return load_strategy_config(CONFIG, ROOT)


@pytest.fixture(scope="module")
def v2_signals(cfg):
    return make_signals(cfg, ROOT)


@pytest.fixture(scope="module")
def v1_signals():
    return pl.read_csv(ROOT / "docs/reference/v1_reference_signals.csv", try_parse_dates=True)


@needs_panel
def test_signals_are_the_same_294_as_v1(v2_signals, v1_signals):
    j = v1_signals.join(v2_signals, on=["symbol", "signal_date"], how="full", suffix="_v2", coalesce=True)
    assert v1_signals.height == v2_signals.height == 294
    assert j.filter(pl.col("entry_ref").is_null() | pl.col("entry_ref_v2").is_null()).is_empty()
    for col in ("entry_ref", "stop", "pivot", "rs_rank", "range10", "voldry"):
        assert ((j[col] / j[f"{col}_v2"]) - 1).abs().max() < 1e-12, col


@needs_panel
def test_v1_port_trades_match_v1_when_signal_rounding_is_removed(cfg, v2_signals, v1_signals):
    """Nine 2010 signals differ from v1's by ~1e-15 (entry_ref, stop). Given v1's exact values for those two columns the
    run is trade-for-trade v1: 258 trades, 6.39% CAGR, 23.55% max drawdown, Calmar 0.27."""
    exact = v2_signals.drop("entry_ref", "stop").join(v1_signals.select("symbol", "signal_date", "entry_ref", "stop"),
                                                     on=["symbol", "signal_date"]).select(v2_signals.columns)
    sim, run = evaluate(cfg, ROOT, cfg.params.engine, exact, load_bars(ROOT, cfg, cfg.params.engine))
    ref = pl.read_csv(ROOT / "docs/reference/v1_reference_trades.csv", try_parse_dates=True)
    j = sim.trades.join(ref, on=["symbol", "signal_date"], how="full", suffix="_ref", coalesce=True)
    assert sim.trades.height == ref.height == 258
    assert j.filter((pl.col("entry_date") != pl.col("entry_date_ref")) | (pl.col("exit_date") != pl.col("exit_date_ref"))).is_empty()
    m = run.metrics["strategy"]
    assert (round(m["cagr_pct"], 2), round(m["max_dd_pct"], 2), round(m["calmar"], 2)) == (6.39, 23.55, 0.27)


@needs_panel
def test_v1_port_as_computed_stays_close_to_v1(cfg, v2_signals):
    """The unpatched run flips one cash-limited fill in 2017 (the cost <= cash check turns on a 1-ulp difference) and
    the change spreads. It stays within a trade and half a point of v1; the exact parity test above is the real gate."""
    _, run = evaluate(cfg, ROOT, cfg.params.engine, v2_signals, load_bars(ROOT, cfg, cfg.params.engine))
    m = run.metrics["strategy"]
    assert abs(m["trades"] - 258) <= 1
    assert abs(m["cagr_pct"] - 6.39) < 0.5 and abs(m["max_dd_pct"] - 23.55) < 1.0
    assert set(run.metrics["baselines"]) == {"nifty500_tri_buy_and_hold", "momentum_12_1"}


# --- baselines -----------------------------------------------------------------------------------------------------

def _market(cost: bool) -> MarketConfig:
    return MarketConfig(slippage_bps_per_side=10.0 if cost else 0.0, buy_charge_rate=0.001 if cost else 0.0,
                        sell_charge_rate=0.001 if cost else 0.0, dp_fee_per_sale_inr=16.0 if cost else 0.0,
                        idle_cash_yield_annual=0.0, trading_days_per_year=252, sector_map_file="x")


def _cfg(tri: str, **over) -> BaselinesConfig:
    mom = dict(lookback_sessions=20, skip_sessions=5, top_n=1, allowed_series=["EQ"], min_price_inr=10.0,
               min_adv_inr=1.0, adv_window_sessions=5, initial_capital=100000.0) | over
    return BaselinesConfig(locked_from=date(2024, 1, 1), folds=[], adoption=Adoption(metric="calmar"), buy_and_hold=BuyAndHold(tri_file=tri), momentum=Momentum(**mom))


def _panel(path: Path, drifts: dict[str, float], n: int = 150) -> list[date]:
    days, d = [], date(2020, 1, 1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    rows = []
    for sym, drift in drifts.items():
        for i, day in enumerate(days):
            px = 100.0 * (1 + drift) ** i
            rows.append((day, sym, "EQ", px, 1e9, px, px))
    pl.DataFrame(rows, schema=["date", "symbol", "series", "close", "turnover", "adj_open", "adj_close"], orient="row").write_parquet(path)
    return days


def test_buy_and_hold_reads_the_tri_window(tmp_path):
    days = _panel(tmp_path / "p.parquet", {"A": 0.0})
    tri = tmp_path / "tri.csv"
    pl.DataFrame({"date": days, "tri": [100.0 * 1.001 ** i for i in range(len(days))]}).write_csv(tri)
    got = equity_metrics(baselines.buy_and_hold_curve(tmp_path, _cfg(str(tri))), days[0], days[-1])
    assert got["end_equity"] / got["start_equity"] == pytest.approx(1.001 ** (len(days) - 1))
    assert got["max_dd_pct"] == 0.0


def _momentum(tmp_path, cfg, market, days):
    curve, rebalances = baselines.momentum_curve(cfg, market, tmp_path / "p.parquet", days[0], days[-1])
    return {**equity_metrics(curve, days[0], days[-1]), "rebalances": rebalances,
            "avg_open_positions": curve["open_positions"].mean()}


def test_momentum_holds_the_strongest_name_and_costs_reduce_the_result(tmp_path):
    days = _panel(tmp_path / "p.parquet", {"UP": 0.004, "FLAT": 0.0, "DOWN": -0.002})
    tri = tmp_path / "tri.csv"
    pl.DataFrame({"date": days, "tri": [1.0] * len(days)}).write_csv(tri)
    free = _momentum(tmp_path, _cfg(str(tri)), _market(False), days)
    paid = _momentum(tmp_path, _cfg(str(tri)), _market(True), days)
    assert free["avg_open_positions"] > 0.7 and free["rebalances"] >= 3
    assert free["cagr_pct"] > 0
    assert paid["end_equity"] < free["end_equity"]
    assert free["max_dd_pct"] == pytest.approx(0.0, abs=1e-9)


def test_momentum_ignores_names_failing_the_liquidity_or_price_filter(tmp_path):
    days = _panel(tmp_path / "p.parquet", {"UP": 0.004, "OTHER": 0.001})
    tri = tmp_path / "tri.csv"
    pl.DataFrame({"date": days, "tri": [1.0] * len(days)}).write_csv(tri)
    all_out = _cfg(str(tri), min_price_inr=1e6)
    got = _momentum(tmp_path, all_out, _market(False), days)
    assert got["avg_open_positions"] == 0 and got["end_equity"] == pytest.approx(100000.0)
