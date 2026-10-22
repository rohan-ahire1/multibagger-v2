"""NSE SAST Regulation 31 encumbrance events (M134): promoters' pledge creation, release and invocation filings.

One file per calendar month of broadcasts, `<raw_dir>/<YYYY-MM>.parquet`, every API field kept as a string. Only months
that have ended are fetched, and an existing month file is never rewritten (raw data is immutable). NSE returns nothing
for broadcasts before 2014.
"""
from __future__ import annotations

import calendar
import logging
import time
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import requests

from mb.config.models import PledgeSource
from mb.sources.http import build_session

LOGGER = logging.getLogger(__name__)
FIELDS = ["symbol", "companyName", "promoterName", "broadcastdate", "reportingDate", "eventDetailsType",
          "eventDetailsTypeEncumb", "eventDetailsFromDate", "eventDetailsToDate", "eventDetailsHolding", "eventDetailsPerc",
          "preeventHoldingPerc", "encumbHolding", "encumbPerc", "postEventHolding", "postEventHoldingPerc", "seqId",
          "attachment"]


def months(first: str, last: str) -> list[str]:
    """'YYYY-MM' labels from first to last inclusive."""
    y, m = map(int, first.split("-"))
    ly, lm = map(int, last.split("-"))
    out = []
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def parse(payload: dict) -> pl.DataFrame:
    """The API's `data` rows as an all-string frame (missing fields null, values stripped)."""
    rows = payload.get("data")
    if rows is None:
        raise ValueError("no data key")
    clean = [{f: (str(r.get(f)).strip() if r.get(f) is not None else None) for f in FIELDS} for r in rows]
    return pl.DataFrame(clean, schema={f: pl.String for f in FIELDS})


def _refresh(session: requests.Session, cfg: PledgeSource) -> None:
    """Cookies from the home and pledged-data pages; their status does not matter."""
    for url in (cfg.home_url, cfg.referer_url):
        try:
            session.get(url, timeout=cfg.timeout_s)
        except requests.RequestException:
            pass


def fetch(cfg: PledgeSource, root: Path, first: str, last: str, today: date) -> tuple[list[str], list[str], list[str]]:
    """Fetch each month in [first, last] that has ended before `today` and has no file yet.
    Returns (written, skipped as existing or not ended, failed)."""
    session = build_session()
    session.headers["Referer"] = cfg.referer_url
    _refresh(session, cfg)
    written, skipped, failed = [], [], []
    for label in months(first, last):
        y, m = map(int, label.split("-"))
        end = date(y, m, calendar.monthrange(y, m)[1])
        out = root / cfg.raw_dir / f"{label}.parquet"
        if out.exists() or end >= today:
            skipped.append(label)
            continue
        params = {"index": "equities", "from_date": f"01-{m:02d}-{y}", "to_date": end.strftime("%d-%m-%Y")}
        for attempt in range(cfg.max_retries):
            try:
                r = session.get(cfg.api_url, params=params, timeout=cfg.timeout_s)
                r.raise_for_status()
                df = parse(r.json())
                break
            except (requests.RequestException, ValueError) as e:
                LOGGER.warning("%s attempt %d: %s", label, attempt + 1, e)
                time.sleep(cfg.request_sleep_s * (attempt + 2))
                _refresh(session, cfg)
        else:
            failed.append(label)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(out)
        written.append(label)
        time.sleep(cfg.request_sleep_s)
    return written, skipped, failed


def load(raw_dir: Path) -> pl.DataFrame:
    """One row per event: symbol, avail (the day after the NSE broadcast), kind (eventDetailsType, lower case: creation,
    release, invocation, ...), encumbrance (eventDetailsTypeEncumb, lower case), pct (eventDetailsPerc, % of the
    company's shares in the event). Identical rows listed twice count once."""
    files = sorted(raw_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no pledge files in {raw_dir}")
    x = pl.concat([pl.read_parquet(f) for f in files]).unique(maintain_order=True)
    return (x.with_columns(pl.col("broadcastdate").str.slice(0, 11).str.to_titlecase()
                           .str.strptime(pl.Date, "%d-%b-%Y", strict=False).alias("day"))
            .filter(pl.col("day").is_not_null() & pl.col("symbol").is_not_null())
            .select(pl.col("symbol"), (pl.col("day") + timedelta(days=1)).alias("avail"),
                    pl.col("eventDetailsType").str.to_lowercase().fill_null("").alias("kind"),
                    pl.col("eventDetailsTypeEncumb").str.to_lowercase().fill_null("").alias("encumbrance"),
                    pl.col("eventDetailsPerc").cast(pl.Float64, strict=False).alias("pct")))
