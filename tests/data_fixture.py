"""A tiny synthetic raw store: 4 stocks, 60 weekday sessions in 2023, one split, one bonus, one delisting."""
from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path
from zipfile import ZipFile

import polars as pl
import yaml

from mb.sources.nse_corporate_actions import SCHEMA

START = date(2023, 1, 2)
N_SESSIONS = 60
SPLIT_SESSION, BONUS_SESSION, DELIST_AFTER = 30, 20, 40


def sessions() -> list[date]:
    out, d = [], START
    while len(out) < N_SESSIONS:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def price(symbol: str, i: int) -> float:
    base = {"AAA": 100.0, "BBB": 200.0, "CCC": 50.0, "DDD": 80.0}[symbol] * (1 + 0.001 * i)
    if symbol == "AAA" and i >= SPLIT_SESSION:
        base /= 2  # 2-for-1 split
    if symbol == "BBB" and i >= BONUS_SESSION:
        base /= 2  # 1:1 bonus
    return round(base, 2)


def _legacy_csv(d: date, rows: list[tuple[str, float]]) -> bytes:
    lines = ["SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,"]
    for sym, p in rows:
        lines.append(f"{sym},EQ,{p},{p * 1.01:.2f},{p * 0.99:.2f},{p},{p},{p},100000,{p * 100000},"
                     f"{d.strftime('%d-%b-%Y').upper()},10,INE{sym}01,")
    return "\n".join(lines).encode()


def write_raw(root: Path) -> None:
    raw = root / "data/raw/nse_bhavcopy" / "2023"
    raw.mkdir(parents=True)
    for i, d in enumerate(sessions()):
        rows = [(s, price(s, i)) for s in ("AAA", "BBB", "DDD") + (("CCC",) if i < DELIST_AFTER else ())]
        with ZipFile(raw / f"{d.isoformat()}.zip", "w") as z:
            z.writestr(f"cm{d:%d%b%Y}bhav.csv", _legacy_csv(d, rows))

    ss = sessions()
    common = {"isin": None, "raw_purpose": "", "original_source_text": "", "parser_rule": "t",
              "parser_version": "t", "confidence": "explicit", "source_date": None, "source": "nse",
              "ratio_num": None, "ratio_den": None, "old_face_value": None, "new_face_value": None,
              "dividend_amount": None}
    actions = [
        {**common, "symbol": "AAA", "ex_date": ss[SPLIT_SESSION], "action_type": "split",
         "old_face_value": 10.0, "new_face_value": 5.0},
        {**common, "symbol": "BBB", "ex_date": ss[BONUS_SESSION], "action_type": "bonus",
         "ratio_num": 1, "ratio_den": 1},
        {**common, "symbol": "DDD", "ex_date": ss[45], "action_type": "dividend", "dividend_amount": 4.0},
    ]
    ca_dir = root / "data/raw/nse_corporate_actions"
    ca_dir.mkdir(parents=True)
    pl.DataFrame(actions, schema=SCHEMA).write_parquet(ca_dir / "ca.parquet")
    (root / "configs/data").mkdir(parents=True)
    (root / "configs/data/overrides.csv").write_text("symbol,ex_date,action_type,source\n")
    (root / "configs/data/verified_moves.csv").write_text("symbol,date,reason,source\n")


def data_config() -> dict:
    return {
        "name": "fixture",
        "bhavcopy": {"raw_dir": "data/raw/nse_bhavcopy", "series": ["EQ"], "legacy_cutoff": date(2024, 1, 1),
                     "archive_base_url": "http://x", "legacy_archive_base_url": "http://y", "timeout_s": 1.0,
                     "max_retries": 1, "request_sleep_s": 0.0},
        "corporate_actions": {"raw_file": "data/raw/nse_corporate_actions/ca.parquet",
                              "coverage_file": "data/raw/nse_corporate_actions/cov.parquet",
                              "overrides_file": "configs/data/overrides.csv",
                              "applied_override_sources": ["manual"], "resymbol_by_isin": True,
                              "verified_moves_file": "configs/data/verified_moves.csv", "url": "http://z", "timeout_s": 1.0,
                              "window_sleep_s": 0.0},
        "adjustment": {"match_window_sessions": 3, "match_tolerance": 1.25, "min_detectable": 1.2,
                       "unexplained_jump": 1.5, "dividend_max_price_fraction": 0.5},
        "checks": {"min_session_rows_ratio": 0.5, "session_rows_lookback": 5, "accepted_thin_sessions": [],
                   "max_session_gap_days": 7, "max_unexplained_jumps": 0, "max_unmatched_share_events": 0,
                   "max_row_count_drift_pct": 5.0},
    }


def write_data_config(root: Path) -> Path:
    p = root / "data.yaml"
    p.write_text(yaml.safe_dump(data_config()))
    return p


def zip_bytes(name: str, content: str) -> bytes:
    buf = io.BytesIO()
    with ZipFile(buf, "w") as z:
        z.writestr(name, content)
    return buf.getvalue()
