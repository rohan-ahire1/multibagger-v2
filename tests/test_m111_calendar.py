"""M111 (docs/research/m111.md): the `close` order, the `hold_sessions` exit, and the turn-of-month signal dates."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import polars as pl

from mb.engine.config import EngineConfigM111
from mb.engine.simulate import simulate
from mb.strategy.calendar.run import signals
from test_m2_engine import bars, days, flat, market


def eng() -> EngineConfigM111:
    return EngineConfigM111(
        entry={"pending_bars": 1, "order": "close"},
        exits={"mode": "hard", "reclaim_sma_sessions": 5, "hold_sessions": 4, "breakeven_r": 1000.0,
               "tighten_r": 1000.0, "max_hold_days": 100000, "stagnation_bars": 100000, "stagnation_max_mfe_r": 0.0,
               "stagnation_max_open_r": 0.0},
        sizing={"risk_per_trade": 1.0, "max_positions": 1, "max_name_pct": 1.0, "max_sector_positions": 0,
                "max_sector_pct": 1.0, "max_heat_pct": 100.0, "default_sector": "X", "uncapped_sectors": []},
        breaker={"half_dd": 1.0, "stop_dd": 1.0, "close_dd": 1.0},
        initial_capital=1000.0, settle_calendar_days=0,
    )


def test_close_order_and_hold_sessions():
    # Signal on day 2; buys at day 3's close (103); sells at day 7's close (107) after 4 sessions held.
    rows = [(100 + i, 100 + i, 100 + i, 100 + i) for i in range(12)]
    sig = pl.DataFrame([{"symbol": "A", "signal_date": days(3)[2], "entry_ref": 102.0, "stop": 51.0, "size_mult": 1.0}])
    t = simulate(sig, bars("A", rows), {}, eng(), market()).trades.row(0, named=True)
    assert (t["entry_date"], t["entry_price"], t["exit_date"], t["exit_price"], t["status"]) == (
        days(4)[3], 103.0, days(8)[7], 107.0, "hold_sessions")


def test_turn_of_month_signal_is_the_session_before_the_second_last():
    d = [date(2020, 1, 27) + timedelta(days=i) for i in range(10)]
    d = [x for x in d if x.weekday() < 5]                  # Jan 27..31, Feb 3..5
    panel = pl.DataFrame({"date": d, "symbol": "IDX", "adj_close": [float(i) for i in range(len(d))]})
    p = SimpleNamespace(symbol="IDX", entry_session_from_end=2, stop_below_ref_pct=0.5, trade=True,
                        engine=SimpleNamespace(entry=SimpleNamespace(order="close")))
    s = signals(panel, p, d[0], d[-1])
    # January: last session Jan 31, second-last Jan 30, so the signal is dated Jan 29. February's last session in the
    # panel is Feb 5, so its signal is Feb 3.
    assert s["signal_date"].to_list() == [date(2020, 1, 29), date(2020, 2, 3)]
    p.trade = False
    assert signals(panel, p, d[0], d[-1]).is_empty()
