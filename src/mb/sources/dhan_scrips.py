"""Dhan scrip master (M137): Dhan's security id for each NSE symbol, needed to place orders.

The file is public (no login). Each fetch is stored gzipped and unchanged as `<raw_dir>/<YYYY-MM-DD>.csv.gz`.
"""
from __future__ import annotations

import gzip
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl
import requests

from mb.config.models import DhanScripSource


@dataclass(frozen=True)
class Scrip:
    security_id: str
    series: str
    tick: float        # rupees (the file gives paise)


def fetch(cfg: DhanScripSource, root: Path, today: date) -> Path:
    """Write today's copy (refuses to overwrite one)."""
    out = root / cfg.raw_dir / f"{today.isoformat()}.csv.gz"
    if out.exists():
        raise ValueError(f"{out} exists; raw snapshots are immutable")
    r = requests.get(cfg.url, timeout=cfg.timeout_s)
    r.raise_for_status()
    if not r.content.startswith(b"SEM_EXM_EXCH_ID,"):
        raise ValueError("unexpected scrip master header")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(r.content))
    return out


def newest(cfg: DhanScripSource, root: Path) -> Path:
    files = sorted((root / cfg.raw_dir).glob("*.csv.gz"))
    if not files:
        raise ValueError(f"no scrip master under {root / cfg.raw_dir}; run `mb data fetch dhan-scrips`")
    return files[-1]


def load(cfg: DhanScripSource, path: Path) -> dict[str, list[Scrip]]:
    """Symbol -> matching rows of the configured exchange, segment and series (a list, so ambiguity is visible)."""
    raw = path.read_bytes()
    df = pl.read_csv(io.BytesIO(gzip.decompress(raw) if path.suffix == ".gz" else raw), infer_schema=False)
    df = df.filter((pl.col("SEM_EXM_EXCH_ID") == cfg.exchange) & (pl.col("SEM_SEGMENT") == cfg.segment)
                   & pl.col("SEM_SERIES").is_in(cfg.series))
    out: dict[str, list[Scrip]] = {}
    for sym, sid, ser, tick in df.select("SEM_TRADING_SYMBOL", "SEM_SMST_SECURITY_ID", "SEM_SERIES",
                                         "SEM_TICK_SIZE").iter_rows():
        out.setdefault(sym, []).append(Scrip(sid, ser, float(tick) / 100.0))
    return out
