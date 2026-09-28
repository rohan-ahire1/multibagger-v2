"""Build-time data checks. A failed check blocks the dataset version."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import polars as pl

from mb.config.models import ChecksConfig


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # pass | fail | skipped
    value: Any
    limit: Any
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _result(name: str, value: float | int, limit: float | int, detail: str = "") -> CheckResult:
    return CheckResult(name, "pass" if value <= limit else "fail", value, limit, detail)


def run_checks(
    panel: pl.DataFrame,
    matches: pl.DataFrame,
    unusable: pl.DataFrame,
    jumps: pl.DataFrame,
    zip_count: int,
    previous_rows: int | None,
    cfg: ChecksConfig,
) -> list[CheckResult]:
    out: list[CheckResult] = []

    dupes = panel.height - panel.select("date", "symbol").n_unique()
    out.append(_result("duplicate_keys", dupes, 0))

    bad_prices = panel.filter(
        (pl.col("close") <= 0) | (pl.col("adj_close") <= 0) | (pl.col("open") <= 0)
        | (pl.col("high") <= 0) | (pl.col("low") <= 0)
    ).height
    out.append(_result("non_positive_prices", bad_prices, 0))

    sessions = panel.group_by("date").len().sort("date")
    out.append(_result("zip_count_vs_sessions", abs(zip_count - sessions.height), 0,
                       f"{zip_count} zips, {sessions.height} sessions"))

    gaps = sessions.select(pl.col("date").diff().dt.total_days().alias("gap"))["gap"].drop_nulls()
    out.append(_result("max_session_gap_days", int(gaps.max() or 0), cfg.max_session_gap_days))

    ratio = (
        sessions.with_columns(
            (pl.col("len") / pl.col("len").rolling_median(cfg.session_rows_lookback).shift(1)).alias("r"))
        .filter(~pl.col("date").is_in(cfg.accepted_thin_sessions))["r"].drop_nulls()
    )
    worst = float(ratio.min()) if len(ratio) else 1.0
    out.append(CheckResult("min_session_rows_ratio", "pass" if worst >= cfg.min_session_rows_ratio else "fail",
                           round(worst, 4), cfg.min_session_rows_ratio, "rows vs trailing median"))

    unmatched = matches.filter(pl.col("status").is_in(["unmatched", "no_prices"])).height + unusable.height
    out.append(_result("unmatched_share_events", unmatched, cfg.max_unmatched_share_events))
    out.append(_result("unexplained_jumps", jumps.height, cfg.max_unexplained_jumps))

    if previous_rows is None:
        out.append(CheckResult("row_count_drift_pct", "skipped", None, cfg.max_row_count_drift_pct,
                               "no previous version"))
    else:
        drift = abs(panel.height - previous_rows) / previous_rows * 100
        out.append(_result("row_count_drift_pct", round(drift, 4), cfg.max_row_count_drift_pct))
    return out
