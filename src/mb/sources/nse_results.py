"""NSE quarterly financial results (M141): sales, net profit and EPS for every listed company, 2005 onwards.

Two raw layers, both immutable (an existing file is never rewritten):
- `<raw_dir>/listings/<SYMBOL>.json`: the corporates-financial-results API's list of filings for one symbol, as fetched.
- `<raw_dir>/detail/<SYMBOL>/<seqNumber>.<html|xml>.gz`: one filing's figures. Old-format filings (to about 2018) are an
  HTML page of label / value rows (Rs lakh); new-format filings are XBRL (`in-bse-fin:` tags, rupees, one context per
  period in the file).

`parse_html` / `parse_xbrl` turn one detail file into the quarter's figures; `load` builds the per-filing frame.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl
import requests

from mb.config.models import ResultsSource
from mb.sources.http import build_session

LOGGER = logging.getLogger(__name__)
LAKH = 1e5


def _refresh(session: requests.Session, cfg: ResultsSource) -> None:
    for url in (cfg.home_url, cfg.referer_url):
        try:
            session.get(url, timeout=cfg.timeout_s)
        except requests.RequestException:
            pass


def _get(session: requests.Session, cfg: ResultsSource, url: str, params: dict | None) -> requests.Response | None:
    for attempt in range(cfg.max_retries):
        try:
            r = session.get(url, params=params, timeout=cfg.timeout_s)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            LOGGER.warning("%s attempt %d: %s", url, attempt + 1, e)
            time.sleep(cfg.request_sleep_s * (attempt + 2))
            _refresh(session, cfg)
    raise RuntimeError(f"failed: {url}")


def _parse_day(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip()[:11], "%d-%b-%Y").date()
    except ValueError:
        return None


def wanted(rows: list[dict], cfg: ResultsSource) -> list[dict]:
    """Listing rows to fetch details for: quarterly, the configured natures, period end on or after `period_from`,
    with a detail link (old HTML page or an XBRL file)."""
    out = []
    for r in rows:
        end = _parse_day(r.get("toDate"))
        if end is None or end < cfg.period_from or r.get("period") != "Quarterly":
            continue
        if r.get("consolidated") not in cfg.natures:
            continue
        if detail_url(r) is None:
            continue
        out.append(r)
    return out


def detail_url(r: dict) -> str | None:
    x = r.get("xbrl") or ""
    if x and not x.endswith("/-") and x.lower().endswith(".xml"):
        return x
    return r.get("resultDetailedDataLink") or None


def fetch(cfg: ResultsSource, root: Path, symbols: list[str]) -> tuple[int, int, list[str]]:
    """Listing then details for each symbol. Returns (listings written, details written, failed symbols)."""
    session = build_session()
    session.headers["Referer"] = cfg.referer_url
    _refresh(session, cfg)
    base = root / cfg.raw_dir
    n_list = n_det = 0
    failed: list[str] = []
    for i, sym in enumerate(symbols):
        try:
            lp = base / "listings" / f"{sym}.json"
            if lp.exists():
                rows = json.loads(lp.read_text())
            else:
                r = _get(session, cfg, cfg.api_url, {"index": "equities", "symbol": sym, "period": "Quarterly"})
                rows = r.json() if r is not None else []
                if not isinstance(rows, list):
                    rows = []
                lp.parent.mkdir(parents=True, exist_ok=True)
                lp.write_text(json.dumps(rows))
                n_list += 1
                time.sleep(cfg.request_sleep_s)
            for row in wanted(rows, cfg):
                url = detail_url(row)
                ext = "xml" if url.lower().endswith(".xml") else "html"
                dp = base / "detail" / sym / f"{row['seqNumber']}.{ext}.gz"
                if dp.exists():
                    continue
                r = _get(session, cfg, url, None)
                if r is None:
                    continue
                dp.parent.mkdir(parents=True, exist_ok=True)
                dp.write_bytes(gzip.compress(r.content))
                n_det += 1
                time.sleep(cfg.request_sleep_s)
        except (RuntimeError, ValueError) as e:
            LOGGER.warning("%s: %s", sym, e)
            failed.append(sym)
        if (i + 1) % 25 == 0:
            LOGGER.info("%d / %d symbols, %d details", i + 1, len(symbols), n_det)
            _refresh(session, cfg)
    return n_list, n_det, failed


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


# Old-format HTML labels (normalised: lower case, single spaces). First match wins.
_HTML_FIELDS = {
    "sales": ["total income from operations (net) ( a + b)", "total income from operations (net)",
              "net sales/income from operation", "net sales/income from operations",
              "(a) net sales/income from operations (net of excise duty)",
              "(a) net sales/income from operations (inclusive of excise duty)", "interest earned"],
    "net_profit": ["net profit (+) / loss (-) for the period", "net profit(+)/loss(-) for the period",
                   "net profit / (loss) for the period", "net profit (loss) for the period"],
    "eps": ["basic eps before extraordinary items (in rs.)", "basic eps for continued and discontinued operations",
            "basic eps for continuing operations"],
    "paid_up": ["paid-up equity share capital", "paid up equity share capital"],
    "face_value": ["face value (in rs.)"],
}
# Labels followed by "(a) basic" and then the value.
_HTML_EPS_HEADERS = ("earnings per share (before extraordinary items)",)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("&nbsp;", " ")).strip().lower()


def parse_html(text: str) -> dict:
    """Old-format page: Rs lakh amounts (sales, net profit, paid-up) converted to rupees; EPS and face value as is."""
    cells = [_norm(c) for c in re.split(r"<[^>]+>", text)]
    cells = [c for c in cells if c]
    out: dict = {k: None for k in _HTML_FIELDS}
    found: dict[str, tuple[int, float]] = {}   # field -> (label priority, value); earlier labels win
    unit = LAKH
    for i, c in enumerate(cells):
        if c.startswith("amount(rs. in") and "crore" in c:
            unit = 1e7
        for k, labels in _HTML_FIELDS.items():
            if k not in found and c in labels and i + 1 < len(cells):
                v = _num(cells[i + 1])
                if v is not None:
                    found[k] = (labels.index(c), v)
                    continue
            if k in found and c in labels and labels.index(c) < found[k][0] and i + 1 < len(cells):
                v = _num(cells[i + 1])
                if v is not None:
                    found[k] = (labels.index(c), v)
        if c.startswith(_HTML_EPS_HEADERS) and i + 2 < len(cells) and cells[i + 1] == "(a) basic":
            v = _num(cells[i + 2])
            if v is not None and "eps" not in found:
                found["eps"] = (0, v)
    for k, (_, v) in found.items():
        out[k] = v
    for k in ("sales", "net_profit", "paid_up"):
        if out[k] is not None:
            out[k] *= unit
    return out


_XBRL_FIELDS = {
    "sales": ["RevenueFromOperations", "InterestEarned", "Income"],
    "net_profit": ["ProfitLossForPeriod", "ProfitLossForThePeriod"],
    "eps": ["BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
            "BasicEarningsLossPerShareFromContinuingOperations", "BasicEarningsPerShareAfterExtraordinaryItems"],
    "paid_up": ["PaidUpValueOfEquityShareCapital"],
    "face_value": ["FaceValueOfEquityShareCapital"],
}


def parse_xbrl(text: str, period_start: date, period_end: date) -> dict:
    """New-format XBRL: values of the context whose period is exactly [period_start, period_end] (the quarter, not the
    year to date). Rupees."""
    ctx = {}
    for m in re.finditer(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', text, re.S):
        s = re.search(r"<xbrli:startDate>([^<]+)<", m.group(2))
        e = re.search(r"<xbrli:endDate>([^<]+)<", m.group(2))
        i = re.search(r"<xbrli:instant>([^<]+)<", m.group(2))
        ctx[m.group(1)] = (s.group(1) if s else None, e.group(1) if e else (i.group(1) if i else None),
                           "<xbrldi:" in m.group(2))
    ok = {k for k, (s, e, dim) in ctx.items()
          if not dim and s == period_start.isoformat() and e == period_end.isoformat()}
    inst = {k for k, (s, e, dim) in ctx.items() if not dim and s is None}
    # Some NSE files use "OneD" / "OneI" (the current quarter / its end) without defining them.
    if "OneD" not in ctx:
        ok.add("OneD")
    if "OneI" not in ctx:
        inst.add("OneI")
    vals: dict[str, float] = {}
    for m in re.finditer(r'<in-bse-fin:([A-Za-z]+)\s+contextRef="([^"]+)"[^>]*>([^<]*)<', text):
        tag, c, v = m.groups()
        if (c in ok or c in inst) and tag not in vals:
            x = _num(v)
            if x is not None:
                vals[tag] = x
    out = {}
    for k, tags in _XBRL_FIELDS.items():
        out[k] = next((vals[t] for t in tags if t in vals), None)
    return out


SCHEMA = {"symbol": pl.String, "seq": pl.String, "nature": pl.String, "period_start": pl.Date, "period_end": pl.Date,
          "filed": pl.Date, "avail": pl.Date, "sales": pl.Float64, "net_profit": pl.Float64, "eps": pl.Float64,
          "paid_up": pl.Float64, "face_value": pl.Float64}


def load(raw_dir: Path) -> pl.DataFrame:
    """One row per fetched filing. `filed` is NSE's filing (or broadcast) date; `avail` the day after, the first
    decision that may use it. Missing figures are null."""
    recs = []
    for lp in sorted((raw_dir / "listings").glob("*.json")):
        sym = lp.stem
        for r in json.loads(lp.read_text()):
            url = detail_url(r)
            if url is None:
                continue
            ext = "xml" if url.lower().endswith(".xml") else "html"
            dp = raw_dir / "detail" / sym / f"{r.get('seqNumber')}.{ext}.gz"
            if not dp.exists():
                continue
            start, end = _parse_day(r.get("fromDate")), _parse_day(r.get("toDate"))
            filed = _parse_day(r.get("filingDate")) or _parse_day(r.get("broadCastDate"))
            if start is None or end is None or filed is None:
                continue
            text = gzip.decompress(dp.read_bytes()).decode("utf-8", errors="replace")
            v = parse_xbrl(text, start, end) if ext == "xml" else parse_html(text)
            recs.append({"symbol": sym, "seq": str(r.get("seqNumber")), "nature": r.get("consolidated"),
                         "period_start": start, "period_end": end, "filed": filed,
                         "avail": filed + timedelta(days=1), **v})
    return pl.DataFrame(recs, schema=SCHEMA)


def eligible_symbols(panel: Path, cfg: ResultsSource) -> list[str]:
    """EQ symbols that met the price floor and the rolling mean-turnover floor on some session from `symbols_from`."""
    u = (pl.scan_parquet(panel)
         .filter(pl.col("series") == "EQ")
         .sort("symbol", "date")
         .with_columns(pl.col("turnover").rolling_mean(cfg.symbols_adv_window_sessions).over("symbol").alias("adv"))
         .filter((pl.col("date") >= cfg.symbols_from) & (pl.col("close") >= cfg.symbols_min_price_inr)
                 & (pl.col("adv") >= cfg.symbols_min_adv_inr))
         .select("symbol").unique().collect())
    return sorted(u["symbol"].to_list())
