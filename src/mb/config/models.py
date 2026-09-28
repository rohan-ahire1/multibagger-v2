"""Strict config models: no defaults, unknown keys are errors."""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class MarketConfig(Strict):
    slippage_bps_per_side: float
    buy_charge_rate: float
    sell_charge_rate: float
    dp_fee_per_sale_inr: float
    idle_cash_yield_annual: float
    trading_days_per_year: int
    sector_map_file: str


class BuyAndHold(Strict):
    tri_file: str


class Momentum(Strict):
    lookback_sessions: int
    skip_sessions: int
    top_n: int
    allowed_series: list[str]
    min_price_inr: float
    min_adv_inr: float
    adv_window_sessions: int
    initial_capital: float


class Fold(Strict):
    name: str
    start: date
    end: date


class Adoption(Strict):
    metric: Literal["calmar", "cagr_pct"]  # a candidate must beat the milestone and both baselines on this, on every fold


class BaselinesConfig(Strict):
    locked_from: date
    folds: list[Fold]
    adoption: Adoption
    buy_and_hold: BuyAndHold
    momentum: Momentum

    @model_validator(mode="after")
    def _folds_ordered_and_unlocked(self) -> BaselinesConfig:
        prev = None
        for f in self.folds:
            if f.end < f.start:
                raise ValueError(f"fold {f.name}: end is before start")
            if prev is not None and f.start <= prev.end:
                raise ValueError(f"fold {f.name} overlaps or precedes {prev.name}")
            if f.end >= self.locked_from:
                raise ValueError(f"fold {f.name} reaches the locked period (from {self.locked_from})")
            prev = f
        return self


class Period(Strict):
    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> Period:
        if self.end < self.start:
            raise ValueError("period.end is before period.start")
        return self


_DATASET_RE = re.compile(r"^[a-z0-9_]+@[A-Za-z0-9._-]+$")


class StrategyConfig(Strict):
    name: str
    version: str
    dataset: str
    market: str
    period: Period
    params: dict[str, Any]

    @field_validator("dataset")
    @classmethod
    def _pinned(cls, v: str) -> str:
        if not _DATASET_RE.match(v):
            raise ValueError("dataset must look like <name>@<version>")
        if v.split("@", 1)[1] == "latest":
            raise ValueError("dataset must be pinned; 'latest' is not allowed")
        return v


class BhavcopySource(Strict):
    raw_dir: str
    series: list[str]
    legacy_cutoff: date
    archive_base_url: str
    legacy_archive_base_url: str
    timeout_s: float
    max_retries: int
    request_sleep_s: float


class CorporateActionsSource(Strict):
    raw_file: str
    coverage_file: str
    overrides_file: str
    # Override rows are applied only if their source is listed. `seed` rows are excluded on purpose.
    applied_override_sources: list[str]
    url: str
    timeout_s: float
    window_sleep_s: float


class AdjustmentConfig(Strict):
    match_window_sessions: int
    match_tolerance: float
    min_detectable: float
    unexplained_jump: float
    dividend_max_price_fraction: float


class ChecksConfig(Strict):
    # A session with fewer rows than this fraction of the trailing median is flagged as partial.
    min_session_rows_ratio: float
    session_rows_lookback: int
    # Sessions reviewed by hand and accepted as thin (checked against the ratio limit only elsewhere).
    accepted_thin_sessions: list[date]
    max_session_gap_days: int
    max_unexplained_jumps: int
    max_unmatched_share_events: int
    max_row_count_drift_pct: float


class DataConfig(Strict):
    name: str
    bhavcopy: BhavcopySource
    corporate_actions: CorporateActionsSource
    adjustment: AdjustmentConfig
    checks: ChecksConfig
