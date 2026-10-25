"""Pullback strategy parameters (docs/research/m108.md). Every value comes from the strategy YAML; nothing here has a default."""
from __future__ import annotations

from typing import Literal

from mb.config.models import Strict
from mb.engine.config import EngineConfigM108


class Universe(Strict):
    allowed_series: list[str]
    min_price_inr: float           # on the raw (unadjusted) close
    min_adv_inr: float             # mean raw ₹ turnover over adv_window_sessions
    adv_window_sessions: int
    min_history_sessions: int      # the symbol's own sessions in the panel, including the day
    exclude_fund_units: bool       # fund ISINs, and every symbol that ever carried one


class RelativeStrength(Strict):
    """Score = sum of weight * return over each lookback, ranked daily as a percentile (0..100) among universe stocks."""
    lookbacks: list[int]
    weights: list[float]


class Setup(Strict):
    trend_sma_sessions: int        # close above this simple average
    rsi_sessions: int              # Wilder RSI
    rsi_max: float                 # RSI at or below this
    min_rs_rank: float             # 0 = no relative-strength rule


class Market(Strict):
    enabled: bool
    benchmark_symbol: str
    sma_sessions: int              # benchmark close above this average on the signal day


class Signal(Strict):
    limit_below_close_pct: float   # entry_ref = close * (1 - this); 0 with the engine's `open` order
    stop_below_ref_pct: float      # disaster stop = entry_ref * (1 - this)


class Params(Strict):
    universe: Universe
    rs: RelativeStrength
    setup: Setup
    market: Market
    signal: Signal
    engine: EngineConfigM108


class SetupM109(Setup):
    """M109: the order of a day's signals. `rsi` = lowest RSI first (M108); `rs` = highest RS score first."""
    rank_by: Literal["rsi", "rs"]


class ParamsM109(Params):
    setup: SetupM109


class SetupM110(SetupM109):
    """M110 (docs/research/m110.md): skip dips that came on heavy volume (likely news). The larger adjusted volume of the
    signal day and the day before, over the mean of the `volume_avg_sessions` sessions before those two, must be at
    most `max_volume_to_avg`."""
    volume_avg_sessions: int
    max_volume_to_avg: float


class ParamsM110(Params):
    setup: SetupM110


class RelativeStrengthM112(Strict):
    """M112: the momentum book's score, return from `lookback_sessions` to `skip_sessions` ago over the standard
    deviation of daily log returns in that window (momentum `return_over_vol`), ranked daily (0..100)."""
    kind: Literal["return_over_vol"]
    lookback_sessions: int
    skip_sessions: int


class ParamsM112(ParamsM110):
    rs: RelativeStrengthM112  # type: ignore[assignment]
