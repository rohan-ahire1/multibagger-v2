"""NSE security-wise delivery position (MTO files): deliverable quantity per symbol, series and session.

One text file per session, `MTO_<DDMMYYYY>.DAT`, same layout since 2005: four header lines, then records
`20,<sr>,<symbol>,<series>,<quantity traded>,<deliverable quantity>,<percent>`. Stored raw as `<year>/<date>.DAT`.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path

import polars as pl
import requests

from mb.config.models import DeliverySource
from mb.sources.http import build_session

LOGGER = logging.getLogger(__name__)


def file_path(raw_dir: Path, d: date) -> Path:
    return raw_dir / str(d.year) / f"{d.isoformat()}.DAT"


def build_url(cfg: DeliverySource, d: date) -> str:
    return f"{cfg.archive_base_url}/MTO_{d:%d%m%Y}.DAT"


def parse_file(path: Path) -> pl.DataFrame:
    d = date.fromisoformat(path.stem)
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        f = line.strip().split(",")
        if len(f) == 7 and f[0] == "20":
            rows.append((f[2].strip(), f[3].strip(), int(f[4]), int(f[5])))
    frame = pl.DataFrame(rows, schema={"symbol": pl.String, "series": pl.String, "traded_qty": pl.Int64,
                                       "deliv_qty": pl.Int64}, orient="row")
    return frame.with_columns(pl.lit(d).alias("date"))


def build_files(raw_dir: Path, first: date | None) -> list[Path]:
    """The stored files a build reads: every session from `first` on (null: all), oldest first."""
    return [p for p in sorted(raw_dir.rglob("*.DAT")) if first is None or date.fromisoformat(p.stem) >= first]


def parse_all(raw_dir: Path, first: date | None) -> pl.DataFrame:
    files = build_files(raw_dir, first)
    if not files:
        raise ValueError(f"no delivery files in {raw_dir}")
    return (pl.concat([parse_file(p) for p in files]).unique(subset=["date", "symbol", "series"], keep="last")
            .select("date", "symbol", "series", "traded_qty", "deliv_qty"))


def fetch(cfg: DeliverySource, raw_dir: Path, sessions: list[date]) -> dict[str, list[date]]:
    """Download the missing files for `sessions` (trading days). Existing files are never touched; 404s are returned."""
    session = build_session()
    got: list[date] = []
    missing: list[date] = []
    for d in sessions:
        target = file_path(raw_dir, d)
        if target.exists():
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
        if resp.status_code == 404 or not resp.content.startswith(b"Security Wise Delivery"):
            missing.append(d)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(resp.content)
            tmp.rename(target)
            got.append(d)
        time.sleep(cfg.request_sleep_s)
    return {"downloaded": got, "missing": missing}
