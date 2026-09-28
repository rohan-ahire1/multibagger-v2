"""NSE bhavcopy adapter: download daily zips into the raw store and parse them to canonical bars.

Ported from v1 (`data_sources/nse_bhavcopy.py`, `storage/bhav_raw_store.py`).
Two file formats exist: the legacy `cm<DD><MON><YYYY>bhav.csv.zip` before `legacy_cutoff`
and the UDiFF `BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip` after it.
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

from mb.config.models import BhavcopySource
from mb.sources.http import bootstrap, build_session

LOGGER = logging.getLogger(__name__)
SOURCE_NAME = "nse_bhavcopy"


def zip_path(raw_dir: Path, d: date) -> Path:
    return raw_dir / str(d.year) / f"{d.isoformat()}.zip"


def list_zips(raw_dir: Path) -> list[Path]:
    return sorted(raw_dir.rglob("*.zip"))


def zip_date(path: Path) -> date:
    return date.fromisoformat(path.stem)


def build_url(cfg: BhavcopySource, d: date) -> str:
    if d < cfg.legacy_cutoff:
        mon = d.strftime("%b").upper()
        return f"{cfg.legacy_archive_base_url}/{d.year}/{mon}/cm{d:%d}{mon}{d.year}bhav.csv.zip"
    return f"{cfg.archive_base_url}/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def security_id(isin: pl.Expr, symbol: pl.Expr, series: pl.Expr) -> pl.Expr:
    """`isin:<ISIN>` when the file carries one, else `fallback:<symbol>:<series>`."""
    clean = isin.cast(pl.Utf8).str.strip_chars()
    has = clean.is_not_null() & (clean != "")
    return (
        pl.when(has)
        .then(pl.concat_str([pl.lit("isin:"), clean]))
        .otherwise(pl.concat_str([pl.lit("fallback:"), symbol, pl.lit(":"), series]))
    )


def _valid_rows() -> pl.Expr:
    return (
        pl.col("date").is_not_null()
        & pl.col("symbol").is_not_null()
        & (pl.col("symbol").str.len_chars() > 0)
        & (pl.col("close") > 0)
        & (pl.col("high") >= pl.col("low"))
        & (pl.col("volume") >= 0)
    )


def _read_member(path: Path) -> pl.DataFrame:
    with ZipFile(path) as archive:
        payload = archive.read(archive.namelist()[0])
    return pl.read_csv(BytesIO(payload), infer_schema_length=200, ignore_errors=False)


def _finish(frame: pl.DataFrame, series: list[str]) -> pl.DataFrame:
    return (
        frame.with_columns(
            security_id(pl.col("isin"), pl.col("symbol"), pl.col("series")).alias("security_id"),
            pl.lit(SOURCE_NAME).alias("source"),
        )
        .select("date", "symbol", "security_id", "series", "open", "high", "low", "close", "volume",
                "turnover", "source")
        .filter(pl.col("series").is_in(series))
        .filter(_valid_rows())
        .unique(subset=["date", "symbol"], keep="first", maintain_order=True)
        .sort(["symbol", "date"])
    )


def _isin(frame: pl.DataFrame) -> pl.Expr:
    return pl.col("ISIN").cast(pl.Utf8).str.strip_chars() if "ISIN" in frame.columns else pl.lit(None, dtype=pl.Utf8)


def _parse_udiff(path: Path, series: list[str]) -> pl.DataFrame:
    frame = _read_member(path)
    frame = frame.with_columns(
        date=pl.coalesce([
            pl.col("TradDt").str.strptime(pl.Date, format=fmt, strict=False)
            for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y")
        ]),
        symbol=pl.col("TckrSymb").cast(pl.Utf8).str.strip_chars(),
        series=pl.col("SctySrs").cast(pl.Utf8).str.strip_chars(),
        isin=_isin(frame),
        open=pl.col("OpnPric").cast(pl.Float64),
        high=pl.col("HghPric").cast(pl.Float64),
        low=pl.col("LwPric").cast(pl.Float64),
        close=pl.col("ClsPric").cast(pl.Float64),
        volume=pl.col("TtlTradgVol").cast(pl.Int64),
        turnover=pl.col("TtlTrfVal").cast(pl.Float64),
    )
    return _finish(frame, series)


def _parse_legacy(path: Path, series: list[str]) -> pl.DataFrame:
    frame = _read_member(path)
    frame = frame.rename({c: c.strip() for c in frame.columns})
    frame = frame.with_columns(
        date=pl.coalesce([
            pl.col("TIMESTAMP").str.strptime(pl.Date, format=fmt, strict=False)
            for fmt in ("%d-%b-%y", "%d-%b-%Y", "%Y-%m-%d")
        ]),
        symbol=pl.col("SYMBOL").cast(pl.Utf8).str.strip_chars(),
        series=pl.col("SERIES").cast(pl.Utf8).str.strip_chars(),
        isin=_isin(frame),
        open=pl.col("OPEN").cast(pl.Float64),
        high=pl.col("HIGH").cast(pl.Float64),
        low=pl.col("LOW").cast(pl.Float64),
        close=pl.col("CLOSE").cast(pl.Float64),
        volume=pl.col("TOTTRDQTY").cast(pl.Int64),
        turnover=pl.col("TOTTRDVAL").cast(pl.Float64),
    )
    return _finish(frame, series)


def parse_zip(path: Path, cfg: BhavcopySource) -> pl.DataFrame:
    """One zip -> canonical bars. Raises if the file cannot be parsed or is empty."""
    d = zip_date(path)
    if d < cfg.legacy_cutoff:
        frame = _parse_legacy(path, cfg.series)
    else:
        try:
            frame = _parse_udiff(path, cfg.series)
        except Exception:  # schema mismatch: fall back to legacy layout
            frame = _parse_legacy(path, cfg.series)
    if frame.is_empty():
        raise ValueError(f"{path}: no valid rows")
    return frame


def parse_all(raw_dir: Path, cfg: BhavcopySource) -> pl.DataFrame:
    zips = list_zips(raw_dir)
    if not zips:
        raise FileNotFoundError(f"no bhavcopy zips under {raw_dir}")
    frames = []
    for p in zips:  # one bad file fails the build
        frame = parse_zip(p, cfg)
        if frame["date"].n_unique() != 1 or frame["date"][0] != zip_date(p):
            raise ValueError(f"{p}: rows are not all dated {zip_date(p)}")
        frames.append(frame)
    return pl.concat(frames).unique(subset=["date", "symbol"], keep="last").sort(["symbol", "date"])


def fetch(cfg: BhavcopySource, raw_dir: Path, start: date, end: date) -> dict[str, list[date]]:
    """Download missing sessions in [start, end]. Existing files are never touched.

    404 means holiday or not yet published; those dates are returned as `missing`.
    """
    session = build_session()
    bootstrap(session, cfg.timeout_s)
    got: list[date] = []
    missing: list[date] = []
    d = start
    while d <= end:
        target = zip_path(raw_dir, d)
        if d.weekday() >= 5 or target.exists():
            d += timedelta(days=1)
            continue
        resp = None
        for attempt in range(cfg.max_retries):
            try:
                resp = session.get(build_url(cfg, d), timeout=cfg.timeout_s)
                if resp.status_code != 404:
                    resp.raise_for_status()
                break
            except requests.RequestException as exc:
                LOGGER.warning("%s attempt %d: %s", d, attempt + 1, exc)
                resp = None
                time.sleep(2**attempt)
        if resp is None:
            raise RuntimeError(f"could not download {d} after {cfg.max_retries} attempts")
        if resp.status_code == 404:
            missing.append(d)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(resp.content)
            tmp.rename(target)
            got.append(d)
        time.sleep(cfg.request_sleep_s)
        d += timedelta(days=1)
    return {"downloaded": got, "missing": missing}
