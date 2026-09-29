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


# M8 options (docs/research/m8.md). They live in subclasses so configs written before M8 still validate as `Params` and
# resolve to the same hash; a config with the extra keys validates as `ParamsM8`.

class RankingM8(Ranking):
    # Null: one lookback. Otherwise each name gets two percentile ranks among the eligible names at the month-end (the
    # score over `lookback_sessions`, and the same score over this lookback with the same skip) and is ordered by their mean.
    second_lookback_sessions: int | None


class PortfolioM8(Portfolio):
    resize_held: bool             # false: a name kept from the last rebalance is not traded; only exits and new names trade
    max_per_sector: int | None    # at most this many picks per industry (market sector map); unmapped names are not capped


class Sizing(Strict):
    # Null: gross 1. Otherwise gross = min(1, target / annualised stdev of the benchmark's daily log returns over the window).
    vol_target_annual: float | None
    vol_benchmark_symbol: str
    vol_window_sessions: int


class ParamsM8(Params):
    ranking: RankingM8
    portfolio: PortfolioM8
    sizing: Sizing
