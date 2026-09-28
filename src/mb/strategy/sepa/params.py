"""SEPA / VCP strategy parameters. Every value comes from the strategy YAML; nothing here has a default."""
from __future__ import annotations

from mb.config.models import Strict
from mb.engine.config import EngineConfig


class Universe(Strict):
    benchmark_symbol: str        # excluded from candidates; RS is measured against it
    allowed_series: list[str]
    min_price_inr: float         # on the raw (unadjusted) close
    min_adv50_inr: float         # 50-day mean of raw turnover
    min_avg_volume_shares: float # 50-day mean of adjusted volume
    min_history_days: int        # bars a symbol must have had in the panel
    max_symbols: int             # per day, keep this many, most liquid first


class TrendTemplate(Strict):
    sma_fast: int
    sma_mid: int
    sma_slow: int
    lookback_52w: int
    max_below_52w_high_pct: float
    min_above_52w_low_pct: float
    sma200_slope_lookback: int


class Setup(Strict):
    base_lookback: int
    atr_period: int
    atr_contraction_factor: float
    base_max_depth_pct: float
    max_range10_pct: float
    max_vol_dryup_ratio: float
    max_extension_from_50sma_pct: float
    contraction_smooth_window: int
    contraction_min_peak_pct: float
    contraction_max_count: int   # a setup with more contractions than this is exhausted


class Breakout(Strict):
    buffer_atr_mult: float       # trigger = pivot * (1 + prior-day ATR% * this)
    vol_mult: float              # breakout-day volume >= this * 50-day mean volume
    vol_max_mult: float
    max_extension_breakout_pct: float


class Risk(Strict):
    entry_buffer_atr_mult: float # entry_ref = pivot * (1 + prior-day ATR% * this)
    struct_stop_atr_mult: float  # stop = entry_ref - prior-day ATR * this, floored by max_stop_pct
    max_stop_pct: float


class RelativeStrength(Strict):
    lookbacks: list[int]
    weights: list[float]
    skip_recent_days: int
    rank_min: float
    rank_max: float


class Selection(Strict):
    skip_months: list[int]       # signals dated in these calendar months are dropped
    range10_max: float
    voldry_max: float
    setup_streak_max: int
    contraction_max: int
    max_signals_per_day: int


class Params(Strict):
    universe: Universe
    trend: TrendTemplate
    setup: Setup
    breakout: Breakout
    risk: Risk
    rs: RelativeStrength
    selection: Selection
    engine: EngineConfig
