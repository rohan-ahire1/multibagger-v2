"""M2 golden tests: small hand-checked scenarios for the engine, metrics and data gate."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
import yaml

from mb.config.models import MarketConfig
from mb.engine.config import EngineConfig
from mb.engine.gate import DataGateError, enforce_data_gate, trades_touching_jumps
from mb.engine.simulate import simulate
from mb.evaluation.metrics import equity_metrics, trade_metrics

ROOT = Path(__file__).resolve().parents[1]
D0 = date(2020, 1, 1)  # a Wednesday; helper skips weekends


def days(n: int) -> list[date]:
    out, d = [], D0
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars(symbol: str, rows: list[tuple[float, float, float, float]], n_total: int | None = None) -> pl.DataFrame:
    """rows are (open, high, low, close), one per session from D0. Padded with the last close to n_total."""
    n_total = n_total or len(rows)
    rows = [tuple(float(x) for x in r) for r in rows]
    rows = rows + [(rows[-1][3],) * 4] * (n_total - len(rows))
    return pl.DataFrame({
        "date": days(n_total), "symbol": symbol,
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows],
    })


def flat(price: float, n: int) -> list[tuple[float, float, float, float]]:
    return [(price, price, price, price)] * n


def signal(symbol: str, on: int, entry_ref: float, stop: float, size_mult: float = 1.0) -> dict:
    return {"symbol": symbol, "signal_date": days(on + 1)[on], "entry_ref": entry_ref, "stop": stop,
            "size_mult": size_mult}


def sig_frame(*rows: dict) -> pl.DataFrame:
    return pl.DataFrame(list(rows), schema={"symbol": pl.String, "signal_date": pl.Date, "entry_ref": pl.Float64,
                                            "stop": pl.Float64, "size_mult": pl.Float64})


def market(**over) -> MarketConfig:
    base = dict(slippage_bps_per_side=0.0, buy_charge_rate=0.0, sell_charge_rate=0.0, dp_fee_per_sale_inr=0.0,
                idle_cash_yield_annual=0.0, trading_days_per_year=252, sector_map_file="unused.csv")
    return MarketConfig(**{**base, **over})


def engine(**over) -> EngineConfig:
    base = {
        "entry": {"pending_bars": 3},
        "exits": {"mode": "ema_hybrid", "breakeven_r": 3.0, "tighten_r": 5.0, "max_hold_days": 150,
                  "stagnation_bars": 15, "stagnation_max_mfe_r": 0.4, "stagnation_max_open_r": 0.0},
        "sizing": {"risk_per_trade": 0.02, "max_positions": 20, "max_name_pct": 0.2, "max_sector_positions": 4,
                   "max_sector_pct": 1.0, "max_heat_pct": 1.0, "default_sector": "UNKNOWN",
                   "uncapped_sectors": ["ETF"]},
        "breaker": {"half_dd": 0.5, "stop_dd": 0.6, "close_dd": 0.7},
        "initial_capital": 1_000_000.0, "settle_calendar_days": 0,
    }
    for k, v in over.items():
        base[k] = {**base[k], **v} if isinstance(v, dict) else v
    return EngineConfig.model_validate(base)


def run(sigs, frames, sectors=None, eng=None, mkt=None):
    return simulate(sig_frame(*sigs), pl.concat(frames), sectors or {}, eng or engine(), mkt or market())


def test_fill_at_entry_ref_then_intraday_stop():
    rows = [(99, 99, 99, 99), (99, 101, 98, 100), (99, 100, 92, 93)] + flat(93, 3)
    r = run([signal("AAA", 0, 100.0, 93.0)], [bars("AAA", rows)])
    t = r.trades.row(0, named=True)
    assert t["entry_date"] == days(2)[1] and t["exit_date"] == days(3)[2]
    assert t["entry_price"] == 100.0 and t["exit_price"] == 93.0
    assert t["shares"] == pytest.approx(2000.0)  # 20% name cap binds (risk sizing would give 2857)
    assert t["pnl"] == pytest.approx(-14000.0)
    assert t["r_multiple"] == pytest.approx(-1.0)
    assert t["status"] == "intraday_stop"


def test_gap_open_below_stop_exits_at_open():
    rows = [(99, 99, 99, 99), (99, 101, 98, 100), (90, 95, 89, 91)] + flat(91, 3)
    t = run([signal("AAA", 0, 100.0, 93.0)], [bars("AAA", rows)]).trades.row(0, named=True)
    assert t["exit_price"] == 90.0 and t["status"] == "stopped"


def test_gap_up_entry_fills_at_open():
    rows = [(99, 99, 99, 99), (104, 106, 103, 105)] + flat(105, 4)
    t = run([signal("AAA", 0, 100.0, 93.0)], [bars("AAA", rows)]).trades.row(0, named=True)
    assert t["entry_price"] == 104.0


def test_signal_cannot_fill_on_its_own_session():
    rows = [(99, 105, 98, 104), (101, 103, 100, 102)] + flat(102, 4)  # day 0 already trades through 100
    t = run([signal("AAA", 0, 100.0, 93.0)], [bars("AAA", rows)]).trades.row(0, named=True)
    assert t["entry_date"] == days(2)[1]


def test_pending_window_counts_the_symbols_sessions():
    rows = flat(90, 8)  # never reaches 100
    r = run([signal("AAA", 0, 100.0, 85.0)], [bars("AAA", rows)])
    assert r.trades.is_empty()
    assert r.skipped.row(0, named=True)["status"] == "not_filled"
    # fills on the 3rd session (pending_bars=3) but not the 4th
    hit3 = flat(90, 3) + [(99, 101, 98, 100)] + flat(100, 3)
    assert run([signal("AAA", 0, 100.0, 85.0)], [bars("AAA", hit3)]).trades.height == 1
    hit4 = flat(90, 4) + [(99, 101, 98, 100)] + flat(100, 3)
    assert run([signal("AAA", 0, 100.0, 85.0)], [bars("AAA", hit4)]).trades.is_empty()


def test_max_positions_blocks_third_entry():
    fr = [bars(s, [(99, 99, 99, 99), (99, 101, 98, 100)] + flat(100, 6)) for s in ("A", "B", "C")]
    r = run([signal(s, 0, 100.0, 90.0) for s in ("A", "B", "C")], fr, eng=engine(sizing={"max_positions": 2}))
    assert sorted(r.trades["symbol"].to_list()) == ["A", "B"]
    assert r.skipped["symbol"].to_list() == ["C"]


def test_sector_position_cap_skips_second_in_sector():
    fr = [bars(s, [(99, 99, 99, 99), (99, 101, 98, 100)] + flat(100, 6)) for s in ("A", "B")]
    r = run([signal("A", 0, 100.0, 90.0), signal("B", 0, 100.0, 90.0)], fr,
            sectors={"A": "Metals", "B": "Metals"}, eng=engine(sizing={"max_sector_positions": 1}))
    assert r.trades["symbol"].to_list() == ["A"]
    assert r.skipped.row(0, named=True)["status"] == "skipped_sector_positions"


def test_uncapped_sector_ignores_position_cap():
    fr = [bars(s, [(99, 99, 99, 99), (99, 101, 98, 100)] + flat(100, 6)) for s in ("A", "B")]
    r = run([signal("A", 0, 100.0, 90.0), signal("B", 0, 100.0, 90.0)], fr,
            sectors={"A": "ETF", "B": "ETF"}, eng=engine(sizing={"max_sector_positions": 1}))
    assert r.trades.height == 2


def test_cash_limits_position_size():
    # three 20% names then a fourth with only 40% cash left is fine, but a 60% risk-free name cap forces cash bound
    fr = [bars(s, [(99, 99, 99, 99), (99, 101, 98, 100)] + flat(100, 6)) for s in ("A", "B", "C")]
    r = run([signal(s, 0, 100.0, 99.0) for s in ("A", "B", "C")], fr,
            eng=engine(sizing={"max_name_pct": 0.5, "risk_per_trade": 0.5}))
    shares = r.trades.sort("symbol")["shares"].to_list()
    assert shares[0] == pytest.approx(5000.0) and shares[1] == pytest.approx(5000.0)  # 50% each
    assert r.trades.height == 2  # nothing left for C (no cash)


def test_stagnation_exit_fills_next_open():
    n = 20
    rows = [(99, 99, 99, 99), (99, 101, 98, 100)] + [(100, 100.5, 99.5, 100)] * (n - 2)
    eng = engine(exits={"stagnation_bars": 5})
    t = run([signal("AAA", 0, 100.0, 90.0)], [bars("AAA", rows)], eng=eng).trades.row(0, named=True)
    # entry on session 1 is bar 1 of holding? bars_held counts sessions after entry: exit flagged on the 5th
    assert t["status"] == "stagnation_next_open"
    assert t["exit_date"] == days(n)[1 + 5 + 1]
    assert t["exit_price"] == 100.0


def test_breakeven_then_ema_trail_exits_next_open():
    up = [(100 * 1.02 ** i,) * 4 for i in range(1, 40)]  # steady climb: breakeven passes 3R quickly
    up = [(p[0], p[0] * 1.001, p[0] * 0.999, p[0]) for p in up]
    top = up[-1][3]
    down = [(top * 0.97 ** i, top * 0.97 ** i, top * 0.97 ** i, top * 0.97 ** i) for i in range(1, 12)]
    rows = [(99, 99, 99, 99), (99, 101, 98, 100)] + up + down
    r = run([signal("AAA", 0, 100.0, 95.0)], [bars("AAA", rows)])
    t = r.trades.row(0, named=True)
    assert t["status"] == "trail_ema_hybrid_next_open"
    closes = [x[3] for x in rows]
    exit_idx = days(len(rows)).index(t["exit_date"])
    assert t["exit_price"] == rows[exit_idx][0]
    # peak R is far above tighten_r, so the 10-EMA (seeded with the first 10 closes' mean) is the active trail
    k = 2 / 11
    ema = [0.0] * len(closes)
    ema[9] = sum(closes[:10]) / 10
    for i in range(10, len(closes)):
        ema[i] = (closes[i] - ema[i - 1]) * k + ema[i - 1]
    assert closes[exit_idx - 1] <= ema[exit_idx - 1]
    assert all(closes[i] > ema[i] for i in range(12, exit_idx - 1))


def test_max_hold_closes_at_close():
    rows = [(99, 99, 99, 99), (99, 101, 98, 100)] + [(100 + 0.05 * i,) * 4 for i in range(1, 30)]
    eng = engine(exits={"max_hold_days": 10, "stagnation_bars": 999})
    t = run([signal("AAA", 0, 100.0, 90.0)], [bars("AAA", rows)], eng=eng).trades.row(0, named=True)
    assert t["status"] == "max_hold" and t["holding_days"] >= 10


def test_drawdown_breaker_closes_everything():
    rows = [(99, 99, 99, 99), (99, 101, 98, 100), (95, 96, 94, 85)] + flat(85, 3)
    eng = engine(breaker={"half_dd": 0.005, "stop_dd": 0.01, "close_dd": 0.02})
    t = run([signal("AAA", 0, 100.0, 90.0)], [bars("AAA", rows)], eng=eng).trades.row(0, named=True)
    assert t["status"] == "drawdown_close" and t["exit_price"] == 85.0


def test_costs_are_applied_to_price_and_cash():
    rows = [(99, 99, 99, 99), (99, 101, 98, 100), (99, 100, 92, 93)] + flat(93, 3)
    m = market(slippage_bps_per_side=10.0, buy_charge_rate=0.00118658, sell_charge_rate=0.00103658,
               dp_fee_per_sale_inr=16.0)
    r = run([signal("AAA", 0, 100.0, 93.0)], [bars("AAA", rows)], mkt=m)
    t = r.trades.row(0, named=True)
    assert t["entry_price"] == pytest.approx(100 * 1.001 * 1.00118658)
    assert t["exit_price"] == pytest.approx(93 * 0.999 * 0.99896342)
    assert t["pnl"] == pytest.approx(t["shares"] * (t["exit_price"] - t["entry_price"]) - 16.0)
    end_cash = r.equity["cash"][-1]
    assert end_cash == pytest.approx(1_000_000 + t["pnl"], abs=1e-6)


def test_idle_cash_earns_yield():
    r = run([], [bars("AAA", flat(100, 10))], mkt=market(idle_cash_yield_annual=0.252))
    assert r.equity["equity"][-1] == pytest.approx(1_000_000 * (1 + 0.252 / 252) ** 10)


def test_open_positions_are_closed_at_the_last_bar_and_flagged():
    rows = [(99, 99, 99, 99), (99, 101, 98, 100)] + flat(102, 3)
    t = run([signal("AAA", 0, 100.0, 90.0)], [bars("AAA", rows)]).trades.row(0, named=True)
    assert t["status"] == "open" and t["exit_price"] == 102.0


def test_missing_columns_fail_loudly():
    with pytest.raises(ValueError, match="missing columns"):
        simulate(pl.DataFrame({"symbol": ["A"]}), bars("A", flat(1, 3)), {}, engine(), market())


def test_breaker_order_is_validated():
    with pytest.raises(ValueError, match="breaker"):
        run([], [bars("A", flat(1, 3))], eng=engine(breaker={"half_dd": 0.6, "stop_dd": 0.5, "close_dd": 0.7}))


def test_metrics_on_a_known_curve():
    dates = days(40)
    eq = pl.DataFrame({"date": dates, "equity": [100.0 + i for i in range(40)]})
    m = equity_metrics(eq, dates[0], dates[-1])
    yrs = (dates[-1] - dates[0]).days / 365.25
    assert m["cagr_pct"] == pytest.approx(((139 / 100) ** (1 / yrs) - 1) * 100)
    assert m["max_dd_pct"] == 0.0 and m["calmar"] is None
    eq2 = eq.with_columns(pl.when(pl.col("date") == dates[20]).then(60.0).otherwise(pl.col("equity")).alias("equity"))
    assert equity_metrics(eq2, dates[0], dates[-1])["max_dd_pct"] == pytest.approx((1 - 60 / 119) * 100)


def test_metrics_refuse_a_short_curve():
    dates = days(5)
    with pytest.raises(ValueError, match="at least"):
        equity_metrics(pl.DataFrame({"date": dates, "equity": [1.0] * 5}), dates[0], dates[-1])


def test_trade_metrics_count_by_entry_date_in_window():
    rows = [(99, 99, 99, 99), (99, 101, 98, 100), (99, 100, 92, 93)] + flat(93, 3)
    r = run([signal("AAA", 0, 100.0, 93.0)], [bars("AAA", rows)])
    d = days(6)
    assert trade_metrics(r.trades, d[0], d[-1])["trades"] == 1
    assert trade_metrics(r.trades, d[3], d[-1])["trades"] == 0


def test_data_gate_flags_trades_held_through_a_jump():
    rows = [(99, 99, 99, 99), (99, 101, 98, 100)] + flat(100, 6)
    trades = run([signal("AAA", 0, 100.0, 90.0)], [bars("AAA", rows)]).trades
    d = days(8)
    inside = pl.DataFrame({"symbol": ["AAA"], "date": [d[4]], "ratio": [0.5]})
    outside = pl.DataFrame({"symbol": ["AAA"], "date": [d[0]], "ratio": [0.5]})
    other = pl.DataFrame({"symbol": ["ZZZ"], "date": [d[4]], "ratio": [0.5]})
    assert trades_touching_jumps(trades, inside).height == 1
    assert trades_touching_jumps(trades, outside).is_empty()
    assert trades_touching_jumps(trades, other).is_empty()
    with pytest.raises(DataGateError, match="AAA"):
        enforce_data_gate(trades, inside)
    enforce_data_gate(trades, outside)


# --- parity with the v1 reference run, on identical signals -----------------------------------------------------

PANEL = ROOT / "data/datasets/nse_research/2026-09-29/panel.parquet"


@pytest.mark.skipif(not PANEL.exists(), reason="research dataset not built on this machine")
def test_v1_reference_trades_reproduced_on_identical_signals():
    start, end = date(2010, 1, 4), date(2026, 3, 17)
    mkt = MarketConfig(**yaml.safe_load((ROOT / "configs/market/nse_cash.yaml").read_text()))
    eng = engine(sizing={"max_sector_positions": 4}, exits={"stagnation_bars": 15}, entry={"pending_bars": 8},
                 settle_calendar_days=220)
    bar_frame = (pl.scan_parquet(PANEL)
                 .filter(pl.col("date").is_between(start, end + timedelta(days=eng.settle_calendar_days)))
                 .select("date", "symbol", pl.col("adj_open").alias("open"), pl.col("adj_high").alias("high"),
                         pl.col("adj_low").alias("low"), pl.col("adj_close").alias("close")).collect())
    sigs = pl.read_csv(ROOT / "docs/reference/v1_reference_signals.csv", try_parse_dates=True).with_columns(
        size_mult=pl.lit(1.0))
    sm = pl.read_csv(ROOT / "configs/reference/sector_map.csv")
    res = simulate(sigs, bar_frame, dict(zip(sm["Symbol"], sm["Industry"])), eng, mkt)

    ref = pl.read_csv(ROOT / "docs/reference/v1_reference_trades.csv", try_parse_dates=True)
    got = res.trades.filter(pl.col("entry_date").is_between(start, end))
    joined = got.join(ref, on=["symbol", "signal_date"], how="full", suffix="_ref", coalesce=True)
    assert got.height == ref.height == 258
    assert joined.filter(pl.col("entry_date").is_null() | pl.col("entry_date_ref").is_null()).is_empty()
    assert joined.filter((pl.col("entry_date") != pl.col("entry_date_ref"))
                         | (pl.col("exit_date") != pl.col("exit_date_ref"))).is_empty()
    for col in ("entry_price", "exit_price", "shares", "pnl"):
        assert ((joined[col] / joined[f"{col}_ref"]) - 1).abs().max() < 1e-9

    m = equity_metrics(res.equity, start, end)
    assert round(m["cagr_pct"], 2) == 6.39 and round(m["max_dd_pct"], 2) == 23.55 and round(m["calmar"], 2) == 0.27
