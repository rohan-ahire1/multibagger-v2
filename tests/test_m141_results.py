"""M141: NSE quarterly results (src/mb/sources/nse_results.py) and the fundamentals buy rules (mb.data.fundamentals)."""
import gzip
import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from mb.config.loader import load_results_config
from mb.data import fundamentals
from mb.sources import nse_results
from mb.strategy.momentum.params import Fundamentals

ROOT = Path(__file__).resolve().parents[1]

OLD_HTML = """<table><tr><td>Description</td><td>Amount(Rs. in lakhs)</td></tr>
<tr><td>Income from Operations</td></tr>
<tr><td>(a) Net Sales/Income from Operations (Net of excise duty)</td><td>44739.00</td></tr>
<tr><td>Total Income from Operations (net) ( a + b)</td><td>46,002.00</td></tr>
<tr><td>Net Profit / (Loss) for the period</td><td>(40.50)</td></tr>
<tr><td>Paid-up Equity Share Capital</td><td>3768.00</td></tr><tr><td>Face Value (in Rs.)</td><td>10.00</td></tr>
<tr><td>Earnings per share (before extraordinary items) (not annualised):</td></tr>
<tr><td>(a) Basic</td><td>-0.11</td></tr></table>"""

XBRL = """<xbrli:xbrl>
<xbrli:context id="Q"><xbrli:entity/><xbrli:period><xbrli:startDate>2019-07-01</xbrli:startDate><xbrli:endDate>2019-09-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="YTD"><xbrli:entity/><xbrli:period><xbrli:startDate>2019-04-01</xbrli:startDate><xbrli:endDate>2019-09-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="QSeg"><xbrli:entity/><xbrli:period><xbrli:startDate>2019-07-01</xbrli:startDate><xbrli:endDate>2019-09-30</xbrli:endDate></xbrli:period><xbrli:scenario><xbrldi:explicitMember dimension="a">b</xbrldi:explicitMember></xbrli:scenario></xbrli:context>
<in-bse-fin:RevenueFromOperations contextRef="QSeg" unitRef="INR">1.00</in-bse-fin:RevenueFromOperations>
<in-bse-fin:RevenueFromOperations contextRef="YTD" unitRef="INR">900.00</in-bse-fin:RevenueFromOperations>
<in-bse-fin:RevenueFromOperations contextRef="Q" unitRef="INR">500.00</in-bse-fin:RevenueFromOperations>
<in-bse-fin:ProfitLossForPeriod contextRef="Q" unitRef="INR">-20.00</in-bse-fin:ProfitLossForPeriod>
<in-bse-fin:BasicEarningsLossPerShareFromContinuingOperations contextRef="Q">-0.2</in-bse-fin:BasicEarningsLossPerShareFromContinuingOperations>
</xbrli:xbrl>"""


def test_config_loads():
    cfg = load_results_config(ROOT / "configs/data/nse_results.yaml")
    assert cfg.natures == ["Non-Consolidated"] and cfg.period_from == date(2007, 1, 1)


def test_parse_html_lakh_brackets_and_label_priority():
    v = nse_results.parse_html(OLD_HTML)
    assert v["sales"] == pytest.approx(46002.0 * 1e5)  # total income wins over net sales
    assert v["net_profit"] == pytest.approx(-40.5 * 1e5)
    assert v["eps"] == pytest.approx(-0.11) and v["face_value"] == 10.0 and v["paid_up"] == pytest.approx(3768e5)


def test_parse_xbrl_takes_the_quarter_context_only():
    v = nse_results.parse_xbrl(XBRL, date(2019, 7, 1), date(2019, 9, 30))
    assert v["sales"] == 500.0 and v["net_profit"] == -20.0 and v["eps"] == -0.2 and v["paid_up"] is None


def test_parse_xbrl_undefined_oned_is_the_quarter():
    x = '<in-bse-fin:ProfitLossForPeriod contextRef="OneD" unitRef="INR">7.00</in-bse-fin:ProfitLossForPeriod>'
    assert nse_results.parse_xbrl(x, date(2019, 7, 1), date(2019, 9, 30))["net_profit"] == 7.0


def test_wanted_and_load(tmp_path):
    cfg = load_results_config(ROOT / "configs/data/nse_results.yaml")
    rows = [{"seqNumber": "1", "period": "Quarterly", "consolidated": "Non-Consolidated", "fromDate": "01-Jul-2019",
             "toDate": "30-Sep-2019", "filingDate": "25-Oct-2019 18:00", "xbrl": "https://x/a.xml",
             "resultDetailedDataLink": None},
            {"seqNumber": "2", "period": "Quarterly", "consolidated": "Consolidated", "fromDate": "01-Jul-2019",
             "toDate": "30-Sep-2019", "filingDate": "25-Oct-2019 18:00", "xbrl": "https://x/b.xml",
             "resultDetailedDataLink": None},
            {"seqNumber": "3", "period": "Quarterly", "consolidated": "Non-Consolidated", "fromDate": "01-Oct-2006",
             "toDate": "31-Dec-2006", "filingDate": "25-Jan-2007 18:00", "xbrl": "https://x/-",
             "resultDetailedDataLink": "https://x/c.html"}]
    assert [r["seqNumber"] for r in nse_results.wanted(rows, cfg)] == ["1"]
    raw = tmp_path / "r"
    (raw / "listings").mkdir(parents=True)
    (raw / "listings" / "ABC.json").write_text(json.dumps(rows))
    (raw / "detail" / "ABC").mkdir(parents=True)
    (raw / "detail" / "ABC" / "1.xml.gz").write_bytes(gzip.compress(XBRL.encode()))
    df = nse_results.load(raw)
    assert df.height == 1
    assert df.row(0, named=True) | {} == {"symbol": "ABC", "seq": "1", "nature": "Non-Consolidated",
                                          "period_start": date(2019, 7, 1), "period_end": date(2019, 9, 30),
                                          "filed": date(2019, 10, 25), "avail": date(2019, 10, 26), "sales": 500.0,
                                          "net_profit": -20.0, "eps": -0.2, "paid_up": None, "face_value": None}


def _filings(rows):
    return pl.DataFrame(rows, schema=["symbol", "seq", "period_end", "avail", "net_profit"], orient="row")


def test_flags_loss_yoy_first_filing_and_staleness():
    q = [date(2018, 12, 31), date(2019, 3, 31), date(2019, 6, 30), date(2019, 9, 30), date(2019, 12, 31)]
    rows = []
    for i, pe in enumerate(q):
        av = date(pe.year + (pe.month == 12), (pe.month % 12) + 1, 15)
        rows.append(("A", f"a{i}", pe, av, [-5.0, 1.0, 1.0, 1.0, 1.0][i]))   # last four sum 4 > 0 after Dec-2019
        rows.append(("B", f"b{i}", pe, av, [3.0, -2.0, -2.0, 1.0, 2.0][i]))  # Dec-19 2 < Dec-18 3: yoy decline
    rows.append(("A", "late", date(2019, 12, 31), date(2020, 6, 1), -100.0))  # a later re-filing is ignored
    rows.append(("B", "b9", date(2019, 3, 31), date(2019, 4, 10), None))      # no profit: dropped
    f = _filings(rows)
    d_oct, d_feb, d_old = date(2019, 10, 20), date(2020, 2, 1), date(2021, 1, 1)
    loss = fundamentals.flags(f, "loss", [d_oct, d_feb, d_old], 200)
    # Oct-2019: A's last four (Dec-18..Sep-19) sum -2 -> flagged; B's sum 0 -> flagged. Feb-2020: A 4, B -1.
    assert loss[d_oct] == {"A": -1.0, "B": -1.0} and loss[d_feb] == {"B": -1.0} and loss[d_old] == {}
    yoy = fundamentals.flags(f, "yoy_decline", [d_oct, d_feb], 200)
    assert yoy[d_oct] == {} and yoy[d_feb] == {"B": -1.0}
    with pytest.raises(ValueError):
        fundamentals.flags(f, "pe", [d_oct], 200)


def test_fundamentals_params_validate():
    Fundamentals(raw_dir="x", rule="loss", max_age_days=200)
    with pytest.raises(ValueError):
        Fundamentals(raw_dir="x", rule="loss", max_age_days=0)
