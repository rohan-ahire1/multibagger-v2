"""NSE corporate-actions adapter: fetch in half-year windows, parse subjects, merge by window.

Ported from v1 `scripts/nse_corporate_actions_fetch.py`. Fetching one window replaces only that
window (v1 trap 7: a fetch of one year used to overwrite the whole file). Unparseable subjects are
kept as `unparsed` with `original_source_text`, never dropped.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from pathlib import Path

import polars as pl

from mb.config.models import CorporateActionsSource
from mb.sources.http import bootstrap, build_session

LOGGER = logging.getLogger(__name__)
PARSER_VERSION = "2026.09.27.1"

_FV_SPLIT = re.compile(
    r"(?:split|sub[-\s]?division).*?(?:from\s*)?(?:rs?|re)\.?\s*(\d+(?:\.\d+)?).*?to\s*(?:rs?|re)\.?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_BONUS = re.compile(r"bonus\s*-?\s*(\d+)\s*:\s*(\d+)", re.IGNORECASE)
_DIV = re.compile(r"dividend.*?(?:rs?|re)\.?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_RIGHTS = re.compile(r"\brights?\s+issue\b", re.IGNORECASE)
_DEMERGER = re.compile(r"\bde[\s-]?merger\b", re.IGNORECASE)
_MERGER = re.compile(r"\bmerger\b|\bamalgamation\b", re.IGNORECASE)
_CONSOLIDATION = re.compile(r"\b(?:reverse\s+split|consolidation)\b", re.IGNORECASE)
_OTHER = re.compile(r"\b(?:scheme\s+of\s+arrangement|capital\s+reduction)\b", re.IGNORECASE)

SCHEMA = {
    "symbol": pl.Utf8, "isin": pl.Utf8, "ex_date": pl.Date, "action_type": pl.Utf8,
    "ratio_num": pl.Int64, "ratio_den": pl.Int64, "old_face_value": pl.Float64,
    "new_face_value": pl.Float64, "dividend_amount": pl.Float64,
    "raw_purpose": pl.Utf8, "original_source_text": pl.Utf8,
    "parser_rule": pl.Utf8, "parser_version": pl.Utf8, "confidence": pl.Utf8,
    "source_date": pl.Date, "source": pl.Utf8,
}
COVERAGE_SCHEMA = {
    "year": pl.Int64, "window_start": pl.Date, "window_end": pl.Date,
    "status": pl.Utf8, "events": pl.Int64,
}
_PARSED_FIELDS = (
    "action_type", "ratio_num", "ratio_den", "old_face_value", "new_face_value",
    "dividend_amount", "parser_rule", "parser_version", "confidence",
)


def parse_subject(subject: str) -> dict[str, object]:
    """Parse an NSE `subject` string. A bonus and a face-value split in one subject give `bonus_split`."""
    s = subject or ""
    out: dict[str, object] = {
        "action_type": "unparsed", "ratio_num": None, "ratio_den": None,
        "old_face_value": None, "new_face_value": None, "dividend_amount": None,
        "raw_purpose": s, "original_source_text": s,
        "parser_rule": "no_explicit_rule", "parser_version": PARSER_VERSION, "confidence": "unverified",
    }
    legs: list[str] = []
    fv = _FV_SPLIT.search(s)
    if fv:
        out["old_face_value"], out["new_face_value"] = float(fv.group(1)), float(fv.group(2))
        legs.append("split")
    bon = _BONUS.search(s)
    if bon:
        out["ratio_num"], out["ratio_den"] = int(bon.group(1)), int(bon.group(2))
        legs.append("bonus")
    if legs:
        out["action_type"] = "bonus_split" if len(legs) == 2 else legs[0]
        out["parser_rule"] = (
            "explicit_bonus_and_face_value_split" if len(legs) == 2
            else "explicit_face_value_split" if legs[0] == "split" else "explicit_bonus_ratio"
        )
        out["confidence"] = "explicit"
        return out
    div = _DIV.search(s)
    if div and "dividend" in s.lower():
        out.update(action_type="dividend", dividend_amount=float(div.group(1)),
                   parser_rule="explicit_dividend_amount", confidence="explicit")
        return out
    for pattern, kind in ((_RIGHTS, "rights"), (_DEMERGER, "demerger"), (_MERGER, "merger"),
                          (_CONSOLIDATION, "consolidation"), (_OTHER, "other")):
        if pattern.search(s):
            out.update(action_type=kind, parser_rule=f"explicit_{kind}", confidence="explicit")
            return out
    return out


def _parse_ex_date(raw: str) -> date | None:
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def fetch_window(session, cfg: CorporateActionsSource, from_d: date, to_d: date) -> list[dict]:
    params = {"index": "equities", "from_date": from_d.strftime("%d-%m-%Y"), "to_date": to_d.strftime("%d-%m-%Y")}
    resp = session.get(cfg.url, params=params, timeout=cfg.timeout_s, headers={"Accept": "application/json"})
    resp.raise_for_status()
    payload = resp.json()
    rows: list[dict] = []
    for item in payload if isinstance(payload, list) else []:
        subject = item.get("subject") or item.get("purpose") or ""
        ex = _parse_ex_date(item.get("exDate") or item.get("ex_date") or "")
        if ex is None:
            continue
        rows.append({
            "symbol": (item.get("symbol") or "").strip(),
            "isin": (item.get("isin") or "").strip() or None,
            "ex_date": ex,
            "source_date": _parse_ex_date(item.get("sourceDate") or ""),
            **parse_subject(subject),
            "source": "nse",
        })
    return rows


def dedupe(actions: pl.DataFrame) -> pl.DataFrame:
    return actions.unique(subset=["symbol", "ex_date", "action_type"], keep="first").sort(
        ["symbol", "ex_date", "action_type"]
    )


def reparse(actions: pl.DataFrame) -> pl.DataFrame:
    """Re-run the current parser over the stored source text; no network."""
    rows = []
    for row in actions.iter_rows(named=True):
        parsed = parse_subject(row["original_source_text"] or row["raw_purpose"] or "")
        rows.append({**row, **{k: parsed[k] for k in _PARSED_FIELDS}})
    return dedupe(pl.DataFrame(rows, schema=SCHEMA))


def merge_fetched(existing: pl.DataFrame | None, fetched: pl.DataFrame,
                  fetched_windows: list[tuple[date, date]]) -> pl.DataFrame:
    """Replace only the windows that were fetched successfully."""
    if existing is None or existing.is_empty():
        return dedupe(fetched)
    in_fetched = pl.lit(False)
    for lo, hi in fetched_windows:
        in_fetched = in_fetched | pl.col("ex_date").is_between(lo, hi)
    kept = existing.filter(~in_fetched).select(list(SCHEMA)).cast(SCHEMA)
    return dedupe(pl.concat([kept, fetched.select(list(SCHEMA)).cast(SCHEMA)]))


def fetch(cfg: CorporateActionsSource, root: Path, start_year: int, end_year: int) -> tuple[pl.DataFrame, list[date]]:
    """Fetch half-year windows and merge into the raw file (never overwrite other windows).

    Returns the merged table and the start dates of windows that failed (they keep their previous data)."""
    out_path, cov_path = root / cfg.raw_file, root / cfg.coverage_file
    existing = pl.read_parquet(out_path) if out_path.exists() else None
    session = build_session()
    bootstrap(session, cfg.timeout_s)
    rows: list[dict] = []
    coverage: list[dict] = []
    ok_windows: list[tuple[date, date]] = []
    for year in range(start_year, end_year + 1):
        for a, b in ((date(year, 1, 1), date(year, 6, 30)), (date(year, 7, 1), date(year, 12, 31))):
            try:
                got = fetch_window(session, cfg, a, b)
                rows.extend(got)
                ok_windows.append((a, b))
                coverage.append({"year": year, "window_start": a, "window_end": b,
                                 "status": "fetched" if got else "empty_unverified", "events": len(got)})
                LOGGER.info("%s..%s: %d events", a, b, len(got))
            except Exception as exc:  # noqa: BLE001 - a failed window keeps its previous data
                coverage.append({"year": year, "window_start": a, "window_end": b,
                                 "status": "fetch_failed", "events": None})
                LOGGER.warning("window %s..%s failed: %s", a, b, exc)
            time.sleep(cfg.window_sleep_s)
    merged = merge_fetched(existing, pl.DataFrame(rows, schema=SCHEMA), ok_windows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.write_parquet(out_path)

    new_cov = pl.DataFrame(coverage, schema=COVERAGE_SCHEMA)
    good, failed = new_cov.filter(pl.col("status") != "fetch_failed"), new_cov.filter(pl.col("status") == "fetch_failed")
    if cov_path.exists():
        prior = pl.read_parquet(cov_path).cast(COVERAGE_SCHEMA)
        new_cov = pl.concat([prior.join(good, on="window_start", how="anti"), good,
                             failed.join(prior, on="window_start", how="anti")]).sort("window_start")
    new_cov.write_parquet(cov_path)
    return merged, [c["window_start"] for c in coverage if c["status"] == "fetch_failed"]
