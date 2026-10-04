"""M113: March tax-loss selling (src/mb/evaluation/tax.py: harvest)."""
from datetime import date

import polars as pl
import pytest

from mb.config.models import HarvestConfig, MarketConfig, TaxConfig
from mb.evaluation.tax import harvest, realised

TAX = TaxConfig(equity_short_rate=0.2, equity_long_rate=0.125, equity_long_exemption_inr=100.0, slab_short_rate=0.3,
                slab_long_rate=0.125, cess=0.0, long_term_days=365, slab_symbols=["G"], advance_tax_dates=["06-15"])
MKT = MarketConfig(slippage_bps_per_side=0.0, buy_charge_rate=0.0, sell_charge_rate=0.0, dp_fee_per_sale_inr=0.0,
                   idle_cash_yield_annual=0.0, trading_days_per_year=252, sector_map_file="x")
DAYS = [date(2021, 3, 1), date(2022, 3, 28), date(2022, 3, 29), date(2022, 3, 30), date(2022, 3, 31), date(2022, 4, 1)]


def book(long_term: bool):
    fills = pl.DataFrame([(DAYS[0], "A", "buy", 10.0, 100.0, -1000.0), (DAYS[0], "B", "buy", 10.0, 100.0, -1000.0)],
                         schema=["date", "symbol", "side", "shares", "price", "cash_flow"], orient="row")
    px = {"A": 90.0, "B": 105.0}  # A at a loss, B at a gain of 50
    bars = pl.DataFrame([(d, s, px[s] + (1.0 if d == DAYS[4] else 0.0), px[s]) for d in DAYS for s in px],
                        schema=["date", "symbol", "open", "close"], orient="row")
    equity = pl.DataFrame({"date": DAYS, "equity": [2000.0] * len(DAYS)})
    h = HarvestConfig(sell_session_from_month_end=2, loss_min_frac=0.02, harvest_long_term_exemption=long_term)
    return harvest(fills, bars, equity, MKT, TAX, h)


def test_loss_sold_at_close_and_bought_back_next_open():
    f, scale = book(False)
    new = f.filter(pl.col("date") > DAYS[0]).sort("date")
    assert new.select("date", "symbol", "side", "shares").rows() == [(DAYS[3], "A", "sell", 10.0), (DAYS[4], "A", "buy", 10.0)]
    gains, lots = realised(f, TAX)
    assert gains["gain"].sum() == pytest.approx(-100.0)
    assert lots["A"][0].day == DAYS[4] and lots["A"][0].cost_per_share == pytest.approx(91.0)
    s = dict(scale.iter_rows())
    assert s[DAYS[3]] == 1.0 and s[DAYS[4]] == pytest.approx(1.0 - 10.0 / 2000.0)  # overnight move 90 -> 91


def test_long_term_gain_up_to_exemption():
    f, _ = book(True)
    gains, _ = realised(f, TAX)
    assert sorted(gains.select("symbol", "bucket").rows()) == [("A", "equity_long"), ("B", "equity_long")]
    assert gains.filter(pl.col("symbol") == "B")["gain"].item() == pytest.approx(50.0)


def test_rebuy_must_stay_in_march():
    with pytest.raises(ValueError):
        HarvestConfig(sell_session_from_month_end=1, loss_min_frac=0.02, harvest_long_term_exemption=False)
