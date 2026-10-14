"""Options book parameters (docs/research/m119.md). Every value comes from the strategy YAML; nothing here has a default."""
from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from mb.config.models import Strict


class Signals(Strict):
    raw_dir: str                   # NSE F&O bhavcopy parquet files, relative to the repo root
    rate_annual: float             # Black-76 discount rate
    min_days_to_expiry: int        # calendar days from the F&O session to the expiry used
    spread_min_m: float            # strike / forward band for the call-put spread pairs (inclusive)
    spread_max_m: float
    skew_put_min_m: float          # OTM put band [min, max) and the target it should be closest to
    skew_put_max_m: float
    skew_put_target_m: float
    skew_call_min_m: float         # ATM call band [min, max]
    skew_call_max_m: float
    skew_call_target_m: float
    volume_sessions: int           # option and stock shares are summed over this many sessions


class Portfolio(Strict):
    signal: Literal["call_put_spread", "skew", "option_volume", "combo", "none"]
    top_frac: float                # picks = ceil(top_frac x universe size), equal weight; "none" holds all (1.0)

    @model_validator(mode="after")
    def _frac(self) -> Portfolio:
        if not 0.0 < self.top_frac <= 1.0:
            raise ValueError("top_frac must be in (0, 1]")
        if (self.signal == "none") != (self.top_frac == 1.0):
            raise ValueError('signal "none" holds the whole universe (top_frac 1.0), and only it does')
        return self


class Params(Strict):
    allowed_series: list[str]      # the stock needs a panel bar in one of these on the decision date
    signals: Signals
    portfolio: Portfolio
    decision_offset_sessions: int  # decide this many sessions before each month's last session
    initial_capital: float
