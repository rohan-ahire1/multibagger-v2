"""NSE F&O bhavcopy (M139): the legacy daily `fo<DD><MON><YYYY>bhav.csv.zip` archive, one parquet per calendar year.

`<raw_dir>/nse_fo_bhav_<YYYY>.parquet` in the schema of the 2009-2020 files copied from india-market-data (columns the
legacy file lacks are null). A year is written only once all its weekdays were fetched (a 404 is a holiday), and an
existing year file is never rewritten (raw data is immutable). Days from `legacy_cutoff` on use NSE's UDiFF format,
which this adapter does not read.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import polars as pl
import requests

from mb.config.models import FoBhavSource
from mb.sources.http import build_session

LOGGER = logging.getLogger(__name__)
SCHEMA = {"d": pl.Date, "instrument": pl.String, "sym": pl.String, "expiry": pl.Date, "strike": pl.Float64,
          "opt": pl.String, "o": pl.Float64, "h": pl.Float64, "l": pl.Float64, "c": pl.Float64, "last": pl.Float64,
          "settle": pl.Float64, "vol": pl.Float64, "val_lakh": pl.Float64, "oi": pl.Float64, "chg_oi": pl.Float64,
          "trades": pl.Float64, "undl": pl.Float64, "lot": pl.Float64, "isin": pl.String}
LEGACY = {"INSTRUMENT": "instrument", "SYMBOL": "sym", "EXPIRY_DT": "expiry", "STRIKE_PR": "strike",
          "OPTION_TYP": "opt", "OPEN": "o", "HIGH": "h", "LOW": "l", "CLOSE": "c", "SETTLE_PR": "settle",
          "CONTRACTS": "vol", "VAL_INLAKH": "val_lakh", "OPEN_INT": "oi", "CHG_IN_OI": "chg_oi", "TIMESTAMP": "d"}


def year_path(raw_dir: Path, year: int) -> Path:
    return raw_dir / f"nse_fo_bhav_{year}.parquet"


def build_url(cfg: FoBhavSource, d: date) -> str:
    mon = d.strftime("%b").upper()
    return f"{cfg.legacy_archive_base_url}/{d.year}/{mon}/fo{d:%d}{mon}{d.year}bhav.csv.zip"


def parse_legacy(content: bytes) -> pl.DataFrame:
    """One legacy zip to the year-file schema."""
    with ZipFile(BytesIO(content)) as z:
        raw = pl.read_csv(z.read(z.namelist()[0]), infer_schema=False)
    raw = raw.select([c for c in raw.columns if c.strip()]).rename(lambda c: c.strip())
    missing = set(LEGACY) - set(raw.columns)
    if missing:
        raise ValueError(f"F&O bhavcopy lacks columns {sorted(missing)}")
    x = raw.select(pl.col(k).str.strip_chars().alias(v) for k, v in LEGACY.items())
    return x.select(
        *(pl.col(c).str.strptime(pl.Date, "%d-%b-%Y").alias(c) if c in ("d", "expiry")
          else pl.col(c).cast(t) if c in x.columns else pl.lit(None, t).alias(c)
          for c, t in SCHEMA.items()))


def fetch(cfg: FoBhavSource, root: Path, first_year: int, last_year: int, today: date) -> tuple[list[int], list[int], dict[int, list[date]]]:
    """Fetch each year in [first_year, last_year] that has ended before `today`, has no file yet and lies before
    `legacy_cutoff`. Returns (written, skipped, failed days by year)."""
    session = build_session()
    written, skipped, failed = [], [], {}
    for y in range(first_year, last_year + 1):
        out = year_path(root / cfg.raw_dir, y)
        if out.exists() or date(y, 12, 31) >= today or date(y, 12, 31) >= cfg.legacy_cutoff:
            skipped.append(y)
            continue
        frames, bad = [], []
        d = date(y, 1, 1)
        while d.year == y:
            if d.weekday() < 5:
                df = _day(session, cfg, d)
                if df is None:
                    bad.append(d)
                elif df.height:
                    frames.append(df)
                time.sleep(cfg.request_sleep_s)
            d += timedelta(days=1)
        if bad:
            failed[y] = bad
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        pl.concat(frames).write_parquet(out)
        written.append(y)
        LOGGER.info("%d: %d sessions", y, len(frames))
    return written, skipped, failed


def _day(session: requests.Session, cfg: FoBhavSource, d: date) -> pl.DataFrame | None:
    """The day's rows; an empty frame for a holiday (404); None if every attempt failed."""
    for attempt in range(cfg.max_retries):
        try:
            r = session.get(build_url(cfg, d), timeout=cfg.timeout_s)
            if r.status_code == 404:
                return pl.DataFrame(schema=SCHEMA)
            r.raise_for_status()
            return parse_legacy(r.content)
        except (requests.RequestException, ValueError) as e:
            LOGGER.warning("%s attempt %d: %s", d, attempt + 1, e)
            time.sleep(cfg.request_sleep_s * (attempt + 2))
    return None


def futures(raw_dir: Path, symbol: str, start: date, end: date) -> pl.DataFrame:
    """Index futures for `symbol` between start and end: d, expiry, o (null when not traded), c; one row per day and
    contract."""
    files = [year_path(raw_dir, y) for y in range(start.year, end.year + 1)]
    gone = [f.name for f in files if not f.exists()]
    if gone:
        raise FileNotFoundError(f"no F&O bhavcopy for {gone} in {raw_dir} (mb data fetch fo-bhav)")
    x = pl.concat([pl.read_parquet(f, columns=["d", "instrument", "sym", "expiry", "o", "c"]) for f in files])
    return (x.filter((pl.col("instrument") == "FUTIDX") & (pl.col("sym") == symbol) & pl.col("d").is_between(start, end)
                     & pl.col("c").is_not_null() & (pl.col("c") > 0))
            .select("d", "expiry", pl.when(pl.col("o") > 0).then(pl.col("o")).alias("o"), "c")
            .unique(["d", "expiry"], keep="first").sort("d", "expiry"))
