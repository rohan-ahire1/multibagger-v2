"""Momentum strategy parameters. Every value comes from the strategy YAML; nothing here has a default."""
from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from mb.config.models import Strict


class Universe(Strict):
    allowed_series: list[str]
    min_price_inr: float          # on the raw close of the decision date
    min_adv_inr: float            # mean raw turnover over adv_window_sessions
    adv_window_sessions: int
    exclude_fund_units: bool      # drop ETFs and other fund units (ISIN starting INF); stocks only


class Ranking(Strict):
    lookback_sessions: int        # momentum = adj_close `skip` sessions ago / adj_close `lookback` sessions ago - 1
    skip_sessions: int
    score: Literal["return", "return_over_vol"]  # return_over_vol divides by the stdev of daily log returns over the same span


class Portfolio(Strict):
    top_n: int                    # names held, equal-weighted, reset at every month-end rebalance
    hold_rank_max: int            # a held name stays while its rank is within this; equal to top_n means no buffer

    @model_validator(mode="after")
    def _buffer(self) -> Portfolio:
        if self.hold_rank_max < self.top_n:
            raise ValueError("hold_rank_max must be >= top_n")
        return self


class Regime(Strict):
    enabled: bool
    benchmark_symbol: str         # its adj_close is compared with its own moving average at each rebalance
    sma_sessions: int
    risk_off_gross: float         # fraction of equity invested while the benchmark is below its average


class Params(Strict):
    universe: Universe
    ranking: Ranking
    portfolio: Portfolio
    regime: Regime
    initial_capital: float
