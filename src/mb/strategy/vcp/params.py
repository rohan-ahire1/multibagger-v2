"""VCP strategy parameters (docs/research/m8_vcp.md). Every value comes from the strategy YAML; nothing here has a default."""
from __future__ import annotations

from mb.config.models import Strict
from mb.engine.config import EngineConfigVCP


class Universe(Strict):
    allowed_series: list[str]
    min_price_inr: float           # on the raw (unadjusted) close
    min_adv_inr: float             # mean raw ₹ turnover over adv_window_sessions
    adv_window_sessions: int
    min_history_sessions: int      # the symbol's own sessions in the panel, including the day


class TrendTemplate(Strict):
    """Minervini's trend template, checked on the close of the day before the breakout."""
    sma_fast: int
    sma_mid: int
    sma_slow: int
    sma_slow_rising_sessions: int  # the slow SMA is above its value this many sessions ago
    range_sessions: int            # the 52-week high and low
    min_above_low_pct: float       # close >= low * (1 + this)
    max_below_high_pct: float      # close >= high * (1 - this)
    min_rs_rank: float


class RelativeStrength(Strict):
    """Score = sum of weight * return over each lookback, ranked daily as a percentile (0..100) among universe stocks."""
    lookbacks: list[int]
    weights: list[float]


class Swings(Strict):
    sessions_each_side: int        # a swing high is the highest high of this many sessions on each side


class Base(Strict):
    max_sessions: int              # the base starts at the highest swing high within this many sessions
    min_sessions: int              # base start to breakout day
    min_contractions: int
    max_contractions: int
    max_first_depth: float
    max_last_depth: float
    max_last_to_first_depth: float  # overall tightening: last depth at most this fraction of the first
    min_pivot_to_base_high: float  # the pivot (last swing high) is at least this fraction of the base-start high


class VolumeDryUp(Strict):
    avg_sessions: int              # volume averages cover the sessions before the day, not the day itself
    max_quiet_day_to_avg: float    # the last contraction needs a session below this multiple of the average


class Breakout(Strict):
    min_volume_to_avg: float


class MarketFilter(Strict):
    """No new signals while the benchmark fails the trend template's price rules (vcp_market_dev)."""
    enabled: bool
    benchmark_symbol: str


class Params(Strict):
    universe: Universe
    trend: TrendTemplate
    rs: RelativeStrength
    swings: Swings
    base: Base
    volume: VolumeDryUp
    breakout: Breakout
    market: MarketFilter
    engine: EngineConfigVCP
