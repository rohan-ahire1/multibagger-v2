"""Engine settings: how a strategy's signals become fills, exits and sizes.

Every value is set in the strategy config. Costs and slippage come from the market profile instead.
"""
from __future__ import annotations

from typing import Literal

from mb.config.models import Strict


class EntryRules(Strict):
    pending_bars: int          # a signal stays live for this many of the symbol's sessions after the signal date


class EntryRulesVCP(EntryRules):
    """VCP entries (M9). A separate model so pre-M9 configs keep their fields and hash."""
    max_open_above_ref_pct: float   # a session opening more than this above entry_ref drops the signal (no chasing)
    max_stop_below_fill_pct: float  # the stop is raised to fill * (1 - this) when the signal's stop is further away


class ExitRules(Strict):
    mode: Literal["ema_hybrid", "ema10", "ema21", "hard"]
    breakeven_r: float         # close at entry + breakeven_r * initial risk lifts the stop to entry
    tighten_r: float           # ema_hybrid: peak R at which the trail switches from the 21 to the 10 EMA
    max_hold_days: int         # calendar days; the position closes at that day's close
    stagnation_bars: int       # sessions held before the stagnation test applies
    stagnation_max_mfe_r: float
    stagnation_max_open_r: float


class ExitRulesVCP(ExitRules):
    """Adds a simple-moving-average trail (M9): after breakeven, a close below the SMA exits at the next open."""
    mode: Literal["ema_hybrid", "ema10", "ema21", "hard", "sma"]
    trail_sma_sessions: int


class SizingRules(Strict):
    risk_per_trade: float      # fraction of equity risked to the stop
    max_positions: int
    max_name_pct: float        # cap on one position's cost as a fraction of equity
    max_sector_positions: int  # 0 disables
    max_sector_pct: float      # 1.0 disables
    max_heat_pct: float        # open risk plus new risk as a fraction of equity
    default_sector: str        # label for symbols missing from the sector map (still capped)
    uncapped_sectors: list[str]


class BreakerRules(Strict):
    half_dd: float             # new-position size halves at this drawdown from peak equity
    stop_dd: float             # no new positions
    close_dd: float            # every position is closed


class EngineConfig(Strict):
    entry: EntryRules
    exits: ExitRules
    sizing: SizingRules
    breaker: BreakerRules
    initial_capital: float
    settle_calendar_days: int  # days after period.end that are simulated so late-exiting trades close for real


class EngineConfigVCP(EngineConfig):
    entry: EntryRulesVCP
    exits: ExitRulesVCP


class EntryRulesM108(EntryRules):
    """Pullback entries (M108). `open` buys at the next session's open; `limit` buys if the low reaches entry_ref, at
    min(open, entry_ref). One position per name."""
    order: Literal["open", "limit"]


class ExitRulesM108(ExitRules):
    """Adds `reclaim` (M108): a close above the SMA of `reclaim_sma_sessions` sells at the next open."""
    mode: Literal["ema_hybrid", "ema10", "ema21", "hard", "reclaim"]
    reclaim_sma_sessions: int


class EngineConfigM108(EngineConfig):
    entry: EntryRulesM108
    exits: ExitRulesM108


class EntryRulesM111(EntryRulesM108):
    """Adds `close` (M111): buys at the close of the first session after the signal (a next-day market-on-close order)."""
    order: Literal["open", "limit", "close"]


class ExitRulesM111(ExitRulesM108):
    """Adds `hold_sessions` (M111): after this many sessions held, the position closes at that session's close.
    0 turns it off."""
    hold_sessions: int


class EngineConfigM111(EngineConfig):
    entry: EntryRulesM111
    exits: ExitRulesM111
