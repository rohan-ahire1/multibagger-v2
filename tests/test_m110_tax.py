"""M110: Indian capital-gains tax on a book's fills (src/mb/evaluation/tax.py)."""
from datetime import date

import polars as pl
import pytest

from mb.config.models import TaxConfig
from mb.evaluation.tax import after_tax, fy_end, realised, unrealised, year_tax

CFG = TaxConfig(equity_short_rate=0.20, equity_long_rate=0.125, equity_long_exemption_inr=125000.0,
                slab_short_rate=0.30, slab_long_rate=0.125, cess=0.04, long_term_days=365, slab_symbols=["GOLD"],
                advance_tax_dates=["06-15", "09-15", "12-15", "03-15"])


def fills(rows):
    return pl.DataFrame(rows, schema={"date": pl.Date, "symbol": pl.String, "side": pl.String, "shares": pl.Float64,
                                      "cash_flow": pl.Float64}, orient="row")


def test_fy_end():
    assert fy_end(date(2025, 3, 31)) == 2025 and fy_end(date(2025, 4, 1)) == 2026


def test_fifo_splits_short_and_long_lots():
    f = fills([(date(2020, 1, 1), "A", "buy", 10.0, -1000.0), (date(2020, 6, 1), "A", "buy", 10.0, -2000.0),
               (date(2021, 3, 1), "A", "sell", 15.0, 3000.0)])
    g, lots = realised(f, CFG)
    # 10 shares from Jan 2020 (425 days: long) at 200-100; 5 from Jun 2020 (273 days: short) at 200-200
    assert g.sort("bucket").select("bucket", "gain").rows() == [("equity_long", 1000.0), ("equity_short", 0.0)]
    assert lots["A"][0].shares == 5.0 and lots["A"][0].cost_per_share == 200.0
    assert unrealised(lots, {"A": 300.0}, date(2021, 7, 1), CFG) == {"equity_long": 500.0}


def test_selling_more_than_held_fails():
    with pytest.raises(ValueError):
        realised(fills([(date(2020, 1, 1), "A", "sell", 1.0, 10.0)]), CFG)


def test_exactly_365_days_is_short_term():
    f = fills([(date(2021, 1, 1), "A", "buy", 1.0, -100.0), (date(2022, 1, 1), "A", "sell", 1.0, 200.0)])
    assert realised(f, CFG)[0]["bucket"].to_list() == ["equity_short"]


def test_year_tax_set_off_exemption_and_carry():
    # short loss 50k offsets slab short (30%) first; long gain 200k minus 125k exemption
    tax, carry = year_tax({"equity_short": -50000.0, "slab_short": 40000.0, "equity_long": 200000.0}, (0.0, 0.0), CFG)
    assert tax == pytest.approx((0 * 0.30 + 0 * 0.20 + (200000 - 10000 - 125000) * 0.125) * 1.04)
    assert carry == (0.0, 0.0)
    # long loss cannot offset short gains; it carries
    tax, carry = year_tax({"equity_short": 10000.0, "equity_long": -30000.0}, (5000.0, 0.0), CFG)
    assert tax == pytest.approx(5000 * 0.20 * 1.04) and carry == (0.0, 30000.0)


def test_after_tax_pays_at_year_end_and_scales():
    days = [date(2021, 3, 30), date(2021, 3, 31), date(2021, 4, 1), date(2021, 4, 2)]
    eq = pl.DataFrame({"date": days, "equity": [1000000.0, 1100000.0, 1100000.0, 1210000.0]})
    g = pl.DataFrame({"date": [date(2021, 3, 31)], "bucket": ["equity_short"], "gain": [100000.0]})
    c = after_tax(eq, g, CFG)
    paid = 100000 * 0.20 * 1.04
    assert c["tax"].to_list() == pytest.approx([0.0, paid, 0.0, 0.0])
    k = (1100000 - paid) / 1100000
    assert c["after"].to_list() == pytest.approx([1000000.0, 1100000 - paid, k * 1100000, k * 1210000])
    # liquidating at the end taxes the open gain, scaled by k
    c2 = after_tax(eq, g, CFG, liquidate={"equity_short": 110000.0})
    assert c2["tax"][-1] == pytest.approx(k * 110000 * 0.20 * 1.04)


def test_advance_tax_then_refund_at_year_end():
    days = [date(2021, 6, 14), date(2021, 6, 15), date(2021, 7, 1), date(2022, 3, 31)]
    eq = pl.DataFrame({"date": days, "equity": [1000000.0] * 4})
    g = pl.DataFrame({"date": [date(2021, 6, 14), date(2021, 7, 1)], "bucket": ["equity_short"] * 2,
                      "gain": [100000.0, -100000.0]})
    c = after_tax(eq, g, CFG)
    paid = 100000 * 0.20 * 1.04
    k = (1000000 - paid) / 1000000
    # the July loss is the smaller book's: k x 100000; what is left of the gain is still taxed
    left = (100000 - k * 100000) * 0.20 * 1.04
    assert c["tax"].to_list() == pytest.approx([0.0, paid, 0.0, left - paid])
    assert c["after"][-1] == pytest.approx(1000000.0 - left)
