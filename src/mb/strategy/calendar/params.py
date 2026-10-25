"""Calendar (turn-of-month) strategy parameters (docs/research/m111.md). Every value comes from the YAML; no defaults."""
from __future__ import annotations

from mb.config.models import Strict
from mb.engine.config import EngineConfigM111


class Params(Strict):
    symbol: str
    entry_session_from_end: int    # 2 = buy at the close of the month's second-last session
    stop_below_ref_pct: float      # disaster stop below the signal-day close
    trade: bool                    # false = no signals (the cash control)
    engine: EngineConfigM111
