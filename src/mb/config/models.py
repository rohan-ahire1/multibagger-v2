"""Strict config models: no defaults, unknown keys are errors."""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class TaxConfig(Strict):
    """Indian capital-gains tax on a book's realised gains (M110). Rates are fractions before cess."""
    equity_short_rate: float           # listed equity held long_term_days or less (STCG, s.111A)
    equity_long_rate: float            # listed equity held longer (LTCG, s.112A), above the yearly exemption
    equity_long_exemption_inr: float   # per financial year, on equity long-term gains after set-off
    slab_short_rate: float             # non-equity funds (gold ETFs) held long_term_days or less: the slab rate
    slab_long_rate: float              # non-equity funds held longer (s.112)
    cess: float                        # health and education cess on the tax
    long_term_days: int                # held more than this many calendar days = long term
    slab_symbols: list[str]            # symbols taxed as non-equity funds
    # Advance-tax dates ("MM-DD"): at the first session on or after each, the tax on the financial year's gains so far
    # is paid up (a capital gain may be paid at the instalment after it arises, without interest). Trued up at year end.
    advance_tax_dates: list[str]

    @field_validator("advance_tax_dates")
    @classmethod
    def _month_days(cls, v: list[str]) -> list[str]:
        for md in v:
            if not re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])", md):
                raise ValueError(f"advance_tax_dates: '{md}' is not MM-DD")
        return v


class HarvestConfig(Strict):
    """M113 March tax-loss selling (src/mb/evaluation/tax.py: harvest)."""
    sell_session_from_month_end: int    # sell at the close of this session counted back from March's last (2 = second-last)
    loss_min_frac: float                # sell a symbol when its open lots, net of sell costs, are this far below cost
    harvest_long_term_exemption: bool   # also realise equity long-term gains up to the unused yearly exemption

    @field_validator("sell_session_from_month_end")
    @classmethod
    def _rebuy_in_march(cls, v: int) -> int:
        if v < 2:
            raise ValueError("sell_session_from_month_end must be >= 2 so the buy-back is still in March")
        return v


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
    # Build from this session on (null: all files). Adjustment is backward, so the kept rows equal the full build's.
    first_date: date | None
    series: list[str]
    legacy_cutoff: date
    archive_base_url: str
    legacy_archive_base_url: str
    timeout_s: float
    max_retries: int
    request_sleep_s: float


class DeliverySource(Strict):
    # M40: NSE security-wise delivery position files (`sources/nse_delivery.py`).
    raw_dir: str
    archive_base_url: str
    timeout_s: float
    max_retries: int
    request_sleep_s: float


class CorporateActionsSource(Strict):
    raw_file: str
    coverage_file: str
    overrides_file: str
    # Override rows are applied only if their source is listed. `seed` rows are excluded on purpose.
    applied_override_sources: list[str]
    # The feed lists an action under the symbol a company has today; bars use the symbol it traded under then. When
    # true, a feed row moves to the symbol its ISIN traded under on the last session before the ex-date.
    resymbol_by_isin: bool
    # Unexplained jumps reviewed by hand and found to be real price moves (not data errors); they leave the jump list.
    verified_moves_file: str
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


class DataConfigM14(DataConfig):
    # M14 (docs/research/m14.md): before adjustment, an old symbol's bars take the later symbol its ISIN moved to, so a
    # renamed stock keeps its history. A subclass, so existing data configs keep their model and hash.
    link_renames_by_isin: bool
    # A link is refused when the old symbol's last bar is more than this many calendar days before the new one's first.
    rename_max_gap_days: int = Field(ge=0)


class DataConfigM40(DataConfigM14):
    # M40 (docs/research/m40.md): the panel gains `deliv_qty`, the session's deliverable quantity (null when NSE
    # published none for that symbol and series). A subclass, so existing data configs keep their model and hash.
    delivery: DeliverySource


class CalendarSource(Strict):
    url: str                  # NSE holiday list (JSON, one list per market segment)
    segment: str              # the cash-market segment key
    raw_dir: str              # dated snapshots, newest used
    timeout_s: float


class PaperAlerts(Strict):
    ntfy_url: str
    topic_env: str            # environment variable holding the ntfy topic; unset means alerts go to the log only
    heartbeat_weekday: int    # 0 = Monday; a short status push on that weekday so silence is noticeable

    @field_validator("heartbeat_weekday")
    @classmethod
    def _weekday(cls, v: int) -> int:
        if not 0 <= v <= 6:
            raise ValueError("heartbeat_weekday must be 0..6")
        return v


class PaperConfig(Strict):
    name: str
    strategy_config: str          # a momentum strategy config; its params, market and baselines are used
    strategy_config_hash: str     # the resolved hash it had when paper trading started; any change is refused
    data_config: str              # the daily dataset is built from this
    start: date                   # the book is cash until the first month-end on or after this date
    initial_capital: float
    keep_datasets: int            # daily dataset versions kept; older ones are deleted (they rebuild from raw)
    max_missing_sessions: int     # trading days the newest data may trail today before a stale-data alert
    replay_max_equity_gap_pct: float  # paper vs backtest-replay equity gap that raises an alert
    calendar: CalendarSource
    alerts: PaperAlerts

    @field_validator("keep_datasets")
    @classmethod
    def _keep(cls, v: int) -> int:
        if v < 1:
            raise ValueError("keep_datasets must be at least 1")
        return v


class IndustrySource(Strict):
    # M125: NSE's four-level industry classification (macro / sector / industry / basic industry) for the symbols listed
    # today (`sources/nse_industry.py`). One snapshot file per fetch date; history is not available from NSE.
    raw_dir: str
    listing_url: str          # NSE's current equity list (CSV with a SYMBOL column)
    quote_url: str            # the quote API; returns secInfo with the classification
    home_url: str             # visited first for cookies
    timeout_s: float
    max_retries: int
    request_sleep_s: float
