"""M110 (docs/research/m110.md): the monthly-rebalanced blend and the pullback heavy-volume filter."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import polars as pl
import pytest

from mb.strategy.blend.run import mix, mix_rebalanced
from test_m2_engine import market


def _sleeve(dates, equity):
    eq = pl.DataFrame({"date": dates, "equity": equity, "cash": equity, "invested_value": [0.0] * len(dates),
                       "open_positions": [0] * len(dates)})
    tr = pl.DataFrame({"symbol": ["X"], "entry_date": [dates[0]], "pnl": [0.0]})
    return SimpleNamespace(equity=eq, trades=tr)


def test_monthly_rebalance_resets_weights_and_charges_the_move():
    dates = [date(2020, 1, 30), date(2020, 1, 31), date(2020, 2, 3), date(2020, 2, 4)]
    a = _sleeve(dates, [100.0, 200.0, 200.0, 400.0])   # doubles twice
    b = _sleeve(dates, [100.0, 100.0, 100.0, 100.0])   # flat
    s = [("a", 0.5, a), ("b", 0.5, b)]
    plain, _, _ = mix(s, 1000.0)
    assert plain["equity"].to_list() == [1000.0, 1500.0, 1500.0, 2500.0]
    # No costs: at the Jan 31 close 1500 is reset to 750/750, so Feb 4 = 750 * 2 + 750 = 2250.
    curve, _, _, cost = mix_rebalanced(s, 1000.0, market())
    assert curve["equity"].to_list() == pytest.approx([1000.0, 1500.0, 1500.0, 2250.0]) and cost == 0.0
    # With costs: 250 moved; round trip = sell (1 - 0.99 * 0.999) + buy (1.01 * 1.001 - 1).
    m = market(slippage_bps_per_side=100.0, buy_charge_rate=0.001, sell_charge_rate=0.001)
    curve, _, _, cost = mix_rebalanced(s, 1000.0, m)
    rt = (1 - 0.99 * 0.999) + (1.01 * 1.001 - 1)
    assert cost == pytest.approx(250 * rt)
    after = (1500.0 - 250 * rt) / 2
    assert curve["equity"].to_list() == pytest.approx([1000.0, 1500.0, 2 * after, after * 2 + after])


def test_heavy_volume_dips_are_skipped():
    from mb.strategy.pullback.params import SetupM110
    from mb.strategy.pullback.run import features
    st = SetupM110(trend_sma_sessions=3, rsi_sessions=2, rsi_max=100.0, min_rs_rank=0.0, rank_by="rsi",
                   volume_avg_sessions=3, max_volume_to_avg=2.0)
    n = 10
    dates = [date(2020, 1, d) for d in range(1, n + 1)]
    vol = [100.0] * 8 + [250.0, 100.0]        # day 9 has 2.5x volume; it and day 10 (lookback 2) are refused
    panel = pl.DataFrame({"date": dates, "symbol": "A", "series": "EQ", "security_id": "isin:INE1",
                          "adj_close": [float(10 + i) for i in range(n)], "close": [float(100 + i) for i in range(n)],
                          "turnover": [1e9] * n, "volume": vol, "adj_volume": vol})
    bench = panel.with_columns(pl.lit("NIFTYBEES").alias("symbol"))
    p = SimpleNamespace(
        universe=SimpleNamespace(allowed_series=["EQ"], min_price_inr=0, min_adv_inr=0, adv_window_sessions=1,
                                 min_history_sessions=1, exclude_fund_units=False),
        rs=SimpleNamespace(lookbacks=[1], weights=[1.0]), setup=st,
        market=SimpleNamespace(enabled=False, benchmark_symbol="NIFTYBEES", sma_sessions=3))
    f = features(pl.concat([panel, bench]), p).filter(pl.col("symbol") == "A")
    ok = dict(zip(f["date"].to_list(), f["setup"].to_list(), strict=True))
    assert ok[dates[7]] is True and ok[dates[8]] is False and ok[dates[9]] is False
