"""M9: VCP swings, base and breakout detection, no look-ahead, and the engine's VCP entry and SMA trail."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from mb.config.loader import load_strategy_config
from mb.engine.config import EngineConfigVCP
from mb.strategy.vcp.pattern import _Alternating, scan, swing_points
from mb.strategy.vcp.run import Scan, signals
from test_m2_engine import bars, days, engine, market, run, signal, sig_frame, simulate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def params():
    return load_strategy_config(ROOT / "strategies/vcp/configs/vcp_dev.yaml", ROOT).params


def _path(points: list[tuple[int, float]]) -> np.ndarray:
    """Piecewise-linear closes through (session, price) points."""
    xs, ys = zip(*points, strict=True)
    return np.interp(np.arange(xs[-1] + 1), xs, ys)


def _vcp(last_low: float = 89.3) -> dict[str, np.ndarray]:
    """A rise to 100, then three contractions (20%, 12%, 6% on closes) and a close through the pivot on high volume."""
    close = _path([(0, 50), (60, 100), (75, 80), (90, 97), (100, 85.4), (110, 95), (116, last_low), (125, 94.8), (126, 99)])
    vol = np.ones(len(close))
    vol[100:125] = 0.8
    vol[110:125] = 0.4
    vol[125] = 0.4
    vol[126] = 2.0
    return {"high": close * 1.002, "low": close * 0.998, "close": close, "volume": vol, "vol_avg": np.ones(len(close))}


def _scan(a: dict[str, np.ndarray], p, upto: int | None = None):
    n = upto or len(a["close"])
    return scan(*(a[c][:n] for c in ("high", "low", "close", "volume", "vol_avg")), np.ones(n, dtype=bool), p)


def test_swing_needs_k_sessions_on_each_side():
    h = np.array([1, 2, 3, 2, 1, 2, 5, 2], dtype=float)
    sh, sl = swing_points(h, h, 2)
    assert sh.nonzero()[0].tolist() == [2]  # the 5 at session 6 has only one session after it
    assert sl.nonzero()[0].tolist() == [4]


def test_equal_highs_keep_the_first_and_repeats_keep_the_extreme():
    h = np.array([1, 3, 3, 1], dtype=float)
    assert swing_points(h, h, 1)[0].nonzero()[0].tolist() == [1]
    a = _Alternating()
    for t, hi, px in [(1, True, 10.0), (3, True, 12.0), (5, True, 11.0), (7, False, 8.0)]:
        a.push(t, hi, px)
    assert (a.t, a.is_high, a.px) == ([3, 7], [True, False], [12.0, 8.0])


def test_a_textbook_vcp_is_found_on_its_breakout_day(params):
    reasons, found = _scan(_vcp(), params)
    assert [f.day for f in found] == [126]
    f = found[0]
    assert [c.high_i for c in f.contractions] == [60, 90, 110]
    depths = [c.depth for c in f.contractions]
    assert depths == sorted(depths, reverse=True) and depths[-1] < 0.10
    assert f.pivot == pytest.approx(95 * 1.002) and f.stop == pytest.approx(89.3 * 0.998)
    assert reasons[-1] == (126, "breakout")


def test_the_scan_never_uses_later_sessions(params):
    a = _vcp()
    full, _ = _scan(a, params)
    for d in (100, 118, 126):
        cut, _ = _scan(a, params, upto=d + 1)
        assert cut[-1] == next(r for r in full if r[0] == d)


def test_each_rule_can_reject_the_pattern(params):
    a = _vcp()
    a["volume"][126] = 1.0
    assert _scan(a, params)[0][-1] == (126, "breakout_volume_low")
    a = _vcp()
    a["volume"][110:126] = 1.5
    assert _scan(a, params)[0][-1] == (126, "volume_not_lower")
    a = _vcp()
    a["volume"][110:126] = 0.9
    assert _scan(a, params)[0][-1] == (126, "no_quiet_day")
    assert _scan(_vcp(last_low=83.0), params)[0][-1] == (126, "not_contracting")
    assert _scan(_vcp(last_low=85.6), params)[0][-1] == (126, "last_too_deep")
    strict = params.model_copy(update={"base": params.base.model_copy(update={"max_last_to_first_depth": 0.2})})
    assert _scan(_vcp(), strict)[0][-1] == (126, "not_tightening")


def test_only_the_first_close_through_the_pivot_is_a_breakout(params):
    a = _vcp()
    a["close"][120] = 95.5  # a close above the 95.19 pivot; the high is left alone so no new swing high forms
    reasons, found = _scan(a, params)
    assert reasons[-1] == (126, "pivot_already_crossed") and not found


# --- engine: VCP entry rules and the SMA trail --------------------------------------------------------------------

def _vcp_engine(**over):
    base = engine().model_dump()
    base["entry"] = {"pending_bars": 1, "max_open_above_ref_pct": 0.05, "max_stop_below_fill_pct": 0.08}
    base["exits"] = {**base["exits"], "mode": "sma", "trail_sma_sessions": 5, "breakeven_r": 2.0,
                     "stagnation_bars": 10_000, "max_hold_days": 10_000}
    for k, v in over.items():
        base[k] = {**base[k], **v}
    return EngineConfigVCP.model_validate(base)


def test_a_gap_beyond_the_chase_limit_drops_the_signal():
    rows = [(99, 99, 99, 99), (106, 107, 105, 106)] + [(106,) * 4] * 5
    r = run([signal("AAA", 0, 100.0, 95.0)], [bars("AAA", rows)], eng=_vcp_engine())
    assert r.trades.is_empty() and r.skipped["status"].to_list() == ["skipped_chase"]


def test_the_stop_is_raised_to_the_limit_below_the_fill():
    rows = [(99, 99, 99, 99), (104, 105, 103, 104)] + [(104,) * 4] * 5
    r = run([signal("AAA", 0, 100.0, 90.0)], [bars("AAA", rows)], eng=_vcp_engine())
    assert r.trades.row(0, named=True)["stop"] == pytest.approx(104 * 0.92)


def test_a_signal_for_a_held_name_is_dropped():
    rows = [(99, 99, 99, 99), (100, 101, 99.5, 100), (100, 101, 99.5, 100)] + [(100,) * 4] * 3
    r = run([signal("AAA", 0, 100.0, 95.0), signal("AAA", 1, 100.0, 95.0)], [bars("AAA", rows)], eng=_vcp_engine())
    assert r.trades.height == 1 and r.skipped["status"].to_list() == ["skipped_held"]


def test_after_breakeven_a_close_below_the_sma_exits_next_open():
    up = [(100 * 1.03 ** i,) * 4 for i in range(1, 15)]
    top = up[-1][3]
    rows = [(99, 99, 99, 99), (100, 101, 99.5, 100)] + up + [(top * 0.9,) * 4, (top * 0.85,) * 4, (top * 0.8,) * 4]
    r = run([signal("AAA", 0, 100.0, 95.0)], [bars("AAA", rows)], eng=_vcp_engine())
    t = r.trades.row(0, named=True)
    assert t["status"] == "trail_sma_next_open"
    i = days(len(rows)).index(t["exit_date"])
    closes = [x[3] for x in rows]
    assert closes[i - 1] < sum(closes[i - 5:i]) / 5 and t["exit_price"] == rows[i][0]


def test_pre_m9_engine_configs_are_unchanged():
    assert type(engine()).__name__ == "EngineConfig"
    r = simulate(sig_frame(signal("AAA", 0, 100.0, 95.0)), bars("AAA", [(99,) * 4, (106, 107, 105, 106)] + [(106,) * 4] * 3),
                 {}, engine(), market())
    assert r.trades.row(0, named=True)["stop"] == 95.0


# --- intraday trigger (vcp_intraday_dev) ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def intraday():
    return load_strategy_config(ROOT / "strategies/vcp/configs/vcp_intraday_dev.yaml", ROOT).params


def test_the_intraday_buy_stop_uses_only_earlier_sessions(intraday):
    reasons, found = _scan(_vcp(), intraday)
    assert found[-1].day == 126 and reasons[-1] == (126, "buy_stop")
    a = _vcp()
    a["volume"][126] = 0.1  # the day's own volume and close cannot matter
    a["close"][126] = 90.0
    assert _scan(a, intraday)[0] == reasons


def test_a_buy_stop_is_used_up_once_price_reaches_the_pivot(intraday):
    a = _vcp()
    a["high"][124] = 95.5  # too late to become a swing high
    reasons, found = _scan(a, intraday)
    assert reasons[-2:] == [(125, "pivot_already_crossed"), (126, "pivot_already_crossed")]
    assert found[-1].day == 124


def test_an_intraday_signal_is_dated_the_session_before(params, intraday):
    _, found = _scan(_vcp(), params)
    frame = pl.DataFrame({"date": days(127), "market_ok_prev": [True] * 127})
    sc = Scan(frame, pl.DataFrame(), {"AAA": found}, {"AAA": 0})
    assert signals(sc, params)["signal_date"].to_list() == [days(127)[126]]
    assert signals(sc, intraday)["signal_date"].to_list() == [days(127)[125]]
