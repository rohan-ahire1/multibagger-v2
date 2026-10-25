"""M144 value book parameters (docs/research/m144.md)."""
from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from mb.config.models import Strict


class Universe(Strict):
    allowed_series: list[str]
    min_price_inr: float          # raw close at the decision
    min_adv_inr: float            # mean raw turnover over adv_window_sessions
    adv_window_sessions: int
    exclude_fund_units: bool      # ISINs starting INF, read from the whole dataset


class Params(Strict):
    # Month-end (or decision_offset_sessions before it) book of the top_n names by earnings yield: trailing four
    # quarters' standalone net profit (NSE results, first filings) / market cap at the decision. Only positive
    # earnings count. Equal weight, traded at the next open.
    universe: Universe
    results_raw_dir: str
    max_age_days: int             # the latest quarter must have ended within this many days of the decision
    score: Literal["earnings_yield"]
    top_n: int
    decision_offset_sessions: int
    initial_capital: float

    @model_validator(mode="after")
    def _check(self) -> Params:
        if self.top_n <= 0 or self.max_age_days <= 0 or self.decision_offset_sessions < 0:
            raise ValueError("need top_n > 0, max_age_days > 0, decision_offset_sessions >= 0")
        return self
