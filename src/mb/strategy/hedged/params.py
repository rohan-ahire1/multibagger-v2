"""Hedged parameters (M139): a momentum book pinned by hash, plus a short index-futures overlay in risk-off."""
from __future__ import annotations

from pydantic import model_validator

from mb.config.models import Strict


class Base(Strict):
    config: str                   # momentum strategy config path, relative to the repo root; its own regime switch off
    config_hash: str              # its resolved-config hash; a changed file is refused


class Hedge(Strict):
    signal_symbol: str            # risk-off at a decision when its adj_close is below its sma_sessions average
    sma_sessions: int
    ratio: float                  # short notional = ratio x book equity at the decision's close
    futures_raw_dir: str          # NSE F&O bhavcopy year files (mb data fetch fo-bhav)
    futures_symbol: str           # FUTIDX symbol
    roll_sessions: int            # hold the nearest expiry with more than this many sessions left; roll at the close
    cost_bps_per_side: float      # of the notional traded: each open, close, resize and each leg of a roll

    @model_validator(mode="after")
    def _check(self) -> Hedge:
        if not 0.0 < self.ratio <= 1.5:
            raise ValueError("ratio must be in (0, 1.5]")
        if self.sma_sessions < 2 or self.roll_sessions < 1 or self.cost_bps_per_side < 0.0:
            raise ValueError("need sma_sessions >= 2, roll_sessions >= 1, cost_bps_per_side >= 0")
        return self


class Params(Strict):
    base: Base
    hedge: Hedge
