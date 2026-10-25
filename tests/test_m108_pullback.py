"""M108 (docs/research/m108.md): the engine's `open` and `limit` entries, the `reclaim` exit, the `rank` fill order,
and the pullback setup."""
from __future__ import annotations

import polars as pl

from mb.engine.config import EngineConfigM108
from mb.engine.simulate import simulate
from test_m2_engine import bars, days, flat, market


def eng(order: str = "limit", max_positions: int = 2, max_hold_days: int = 1000) -> EngineConfigM108:
    return EngineConfigM108(
        entry={"pending_bars": 1, "order": order},
        exits={"mode": "reclaim", "reclaim_sma_sessions": 3, "breakeven_r": 1000.0, "tighten_r": 1000.0,
               "max_hold_days": max_hold_days, "stagnation_bars": 100000, "stagnation_max_mfe_r": 0.0,
               "stagnation_max_open_r": 0.0},
        sizing={"risk_per_trade": 1.0, "max_positions": max_positions, "max_name_pct": 0.5, "max_sector_positions": 0,
                "max_sector_pct": 1.0, "max_heat_pct": 100.0, "default_sector": "X", "uncapped_sectors": []},
        breaker={"half_dd": 1.0, "stop_dd": 1.0, "close_dd": 1.0},
        initial_capital=1000.0, settle_calendar_days=0,
    )


def sigs(*rows: tuple[str, int, float, float, int]) -> pl.DataFrame:
    return pl.DataFrame([{"symbol": s, "signal_date": days(on + 1)[on], "entry_ref": ref, "stop": stop, "size_mult": 1.0,
                          "rank": rank} for s, on, ref, stop, rank in rows],
                        schema={"symbol": pl.String, "signal_date": pl.Date, "entry_ref": pl.Float64, "stop": pl.Float64,
                                "size_mult": pl.Float64, "rank": pl.Int64})


def test_limit_fills_at_min_of_open_and_limit_only_if_low_reaches_it():
    # Day 3 signal, limit 97. Day 4: open 99, low 96 -> fills at 97.
    b = bars("A", flat(100, 3) + [(100, 100, 100, 100), (99, 99, 96, 98)] + flat(98, 5))
    r = simulate(sigs(("A", 3, 97.0, 80.0, 0)), b, {}, eng("limit"), market())
    assert r.trades["entry_price"].to_list() == [97.0]
    # Gap below the limit: fills at the open.
    b = bars("A", flat(100, 4) + [(95, 99, 94, 98)] + flat(98, 5))
    assert simulate(sigs(("A", 3, 97.0, 80.0, 0)), b, {}, eng("limit"), market()).trades["entry_price"].to_list() == [95.0]
    # Low stays above the limit: no fill, and the signal lapses after one session.
    b = bars("A", flat(100, 4) + [(99, 99, 98, 98)] + flat(90, 5))
    r = simulate(sigs(("A", 3, 97.0, 80.0, 0)), b, {}, eng("limit"), market())
    assert r.trades.is_empty() and r.skipped["status"].to_list() == ["not_filled"]


def test_open_order_fills_at_the_open_and_reclaim_sells_next_open():
    # Bought at day 4's open 90. SMA(3) of closes: day 5 = (100+90+92)/3 = 94, close 92 stays below; day 6 closes
    # 99 > (90+92+99)/3 = 93.7 -> sells at day 7's open 101.
    rows = flat(100, 4) + [(90, 91, 89, 90), (91, 93, 90, 92), (93, 99, 92, 99), (101, 102, 100, 101)] + flat(101, 3)
    r = simulate(sigs(("A", 3, 100.0, 50.0, 0)), bars("A", rows), {}, eng("open"), market())
    t = r.trades.row(0, named=True)
    assert (t["entry_price"], t["exit_price"], t["status"]) == (90.0, 101.0, "reclaim_next_open")
    assert t["shares"] == 1000.0 * 0.5 / 90.0


def test_rank_sets_fill_order_within_a_day():
    # One slot; B ranks first although A sorts first by symbol.
    b = pl.concat([bars("A", flat(100, 10)), bars("B", flat(100, 10))])
    r = simulate(sigs(("A", 3, 100.0, 50.0, 1), ("B", 3, 100.0, 50.0, 0)), b, {}, eng("open", max_positions=1), market())
    assert r.trades["symbol"].to_list() == ["B"]
