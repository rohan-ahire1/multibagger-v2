"""NSE industry classification (M125): macro / sector / industry / basic industry per listed symbol.

NSE publishes only today's classification, so a snapshot is stored per fetch date as
`<raw_dir>/<YYYY-MM-DD>.parquet` (symbol, isin, macro, sector, industry, basic_industry). Symbols listed today only:
delisted names have no class (a survivorship limit any user of this file must state).
"""
from __future__ import annotations

import io
import logging
import time
from datetime import date
from pathlib import Path

import polars as pl
import requests

from mb.config.models import IndustrySource
from mb.sources.http import build_session

LOGGER = logging.getLogger(__name__)
COLUMNS = {"symbol": pl.String, "isin": pl.String, "macro": pl.String, "sector": pl.String, "industry": pl.String,
           "basic_industry": pl.String}


def parse_quote(payload: dict) -> dict[str, str | None]:
    """The classification from one GetQuoteApi getSymbolData response; blanks become null."""
    rows = payload.get("equityResponse") or []
    if not rows:
        raise ValueError("no equityResponse")
    meta, sec = rows[0].get("metaData") or {}, rows[0].get("secInfo") or {}

    def clean(v: object) -> str | None:
        v = str(v).strip() if v is not None else ""
        return v or None

    return {"symbol": clean(meta.get("symbol")), "isin": clean(meta.get("isinCode")), "macro": clean(sec.get("macro")),
            "sector": clean(sec.get("sector")), "industry": clean(sec.get("industryInfo")),
            "basic_industry": clean(sec.get("basicIndustry"))}


def _refresh(session: requests.Session, cfg: IndustrySource) -> None:
    """Cookies from the home page; its status (often 403) does not matter."""
    try:
        session.get(cfg.home_url, timeout=cfg.timeout_s)
    except requests.RequestException:
        pass


def listed_symbols(session: requests.Session, cfg: IndustrySource) -> list[str]:
    r = session.get(cfg.listing_url, timeout=cfg.timeout_s)
    r.raise_for_status()
    return sorted(pl.read_csv(io.BytesIO(r.content))["SYMBOL"].cast(pl.String).str.strip_chars().to_list())


def fetch(cfg: IndustrySource, root: Path, today: date) -> tuple[Path, list[str]]:
    """Write today's snapshot (refuses to overwrite one). Returns the file and the symbols that failed."""
    out = root / cfg.raw_dir / f"{today.isoformat()}.parquet"
    if out.exists():
        raise ValueError(f"{out} exists; raw snapshots are immutable")
    session = build_session()
    _refresh(session, cfg)
    rows, failed = [], []
    for sym in listed_symbols(session, cfg):
        for attempt in range(cfg.max_retries):
            try:
                r = session.get(cfg.quote_url, params={"functionName": "getSymbolData", "marketType": "N",
                                                       "series": "EQ", "symbol": sym}, timeout=cfg.timeout_s)
                r.raise_for_status()
                rows.append({**parse_quote(r.json()), "symbol": sym})
                break
            except (requests.RequestException, ValueError) as e:
                LOGGER.warning("%s attempt %d: %s", sym, attempt + 1, e)
                time.sleep(cfg.request_sleep_s * (attempt + 2))
                _refresh(session, cfg)
        else:
            failed.append(sym)
        time.sleep(cfg.request_sleep_s)
    out.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows, schema=COLUMNS).write_parquet(out)
    return out, failed


def load(raw_dir: Path, snapshot: str) -> pl.DataFrame:
    """One stored snapshot (file stem = fetch date)."""
    return pl.read_parquet(raw_dir / f"{snapshot}.parquet")
