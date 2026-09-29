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


# M10 options (docs/research/m10.md), again in subclasses so M8 configs keep their model and hash.

class RankingM10(RankingM8):
    # Set: score = adj_close / highest adj_high over this many sessions, the decision date included (George & Hwang 2004).
    # Ties (many names sit at 1.0) are broken by the `score` above.
    high_window_sessions: int | None
    # Set: residual momentum (Blitz, Huij & Martens 2011). Daily log returns are regressed on the benchmark's over this
    # many sessions ending `skip_sessions` before the decision date; score = sum / stdev of the residuals over the
    # lookback-to-skip span.
    residual_beta_sessions: int | None
    residual_benchmark_symbol: str
    # Set: the best ceil(this x top_n) names by the score are reordered by information discreteness, lowest first
    # (Da, Gurun & Warachka 2014), ties by the score; the rest follow in score order.
    frog_candidates_per_slot: float | None

    @model_validator(mode="after")
    def _one_score(self) -> RankingM10:
        scores = [k for k in ("high_window_sessions", "residual_beta_sessions", "second_lookback_sessions")
                  if getattr(self, k) is not None]
        if len(scores) > 1:
            raise ValueError(f"at most one of these ranking options may be set: {', '.join(scores)}")
        if self.residual_beta_sessions is not None and self.residual_beta_sessions < self.lookback_sessions - self.skip_sessions:
            raise ValueError("residual_beta_sessions must cover the lookback-to-skip span")
        if self.frog_candidates_per_slot is not None and self.frog_candidates_per_slot < 1.0:
            raise ValueError("frog_candidates_per_slot must be at least 1")
        return self


class ParamsM10(ParamsM8):
    ranking: RankingM10


# M11 options (docs/research/m11.md), again in subclasses so M10 configs keep their model and hash.

class Schedule(Strict):
    decision_offset_sessions: int  # decide this many sessions before each month's last session; 0 = the month-end

    @model_validator(mode="after")
    def _offset(self) -> Schedule:
        if self.decision_offset_sessions < 0:
            raise ValueError("decision_offset_sessions must be >= 0")
        return self


class Exits(Strict):
    # Set: a name closing at or below (1 - this) x its open at the last rebalance session is sold at the next open; the
    # cash waits for the next rebalance (Han, Zhou & Zhu 2016).
    stop_loss_frac: float | None

    @model_validator(mode="after")
    def _frac(self) -> Exits:
        if self.stop_loss_frac is not None and not 0.0 < self.stop_loss_frac < 1.0:
            raise ValueError("stop_loss_frac must be between 0 and 1")
        return self


class PortfolioM11(PortfolioM8):
    weighting: Literal["equal", "inverse_vol"]
    inverse_vol_sessions: int     # inverse_vol: weight = 1 / stdev of daily log returns over this many sessions to the decision date


class ParamsM11(ParamsM10):
    portfolio: PortfolioM11
    schedule: Schedule
    exits: Exits


# M12 options (docs/research/m12.md).

class RankingM12(RankingM10):
    # Set: at each decision date the ceil(this x n) ranked names with the highest one-day simple return over
    # `max_window_sessions` (decision date included) are removed (Bali, Cakici & Whitelaw 2011).
    max_filter_frac: float | None
    max_window_sessions: int

    @model_validator(mode="after")
    def _max(self) -> RankingM12:
        if self.max_filter_frac is not None and not 0.0 < self.max_filter_frac < 1.0:
            raise ValueError("max_filter_frac must be between 0 and 1")
        return self


class PortfolioM12(PortfolioM11):
    # Set: a name is ranked only if its lookback-to-skip return is above this; each slot stays 1 / top_n, so empty
    # slots are cash (Antonacci's absolute momentum).
    min_momentum: float | None


class ParamsM12(ParamsM11):
    ranking: RankingM12
    portfolio: PortfolioM12


# M13 option (docs/research/m13.md).

class UniverseM13(Universe):
    # With exclude_fund_units: also drop a symbol that has an `isin:INF` id on any row of the panel read (older
    # bhavcopies have no ISIN, so a fund's early rows carry a `fallback:` id).
    fund_units_by_symbol: bool

    @model_validator(mode="after")
    def _needs_exclude(self) -> UniverseM13:
        if self.fund_units_by_symbol and not self.exclude_fund_units:
            raise ValueError("fund_units_by_symbol needs exclude_fund_units")
        return self


class ParamsM13(ParamsM12):
    universe: UniverseM13


# M19 option (docs/research/m19.md).

class PortfolioM19(PortfolioM12):
    # Each symbol here is held at its weight of equity at every decision date, outside the ranking and universe filters;
    # the picks share the rest with their usual relative weights.
    fixed_weights: dict[str, float]

    @model_validator(mode="after")
    def _fixed(self) -> PortfolioM19:
        if any(not w > 0.0 for w in self.fixed_weights.values()) or not sum(self.fixed_weights.values()) < 1.0:
            raise ValueError("fixed_weights must be positive and sum to less than 1")
        return self


class ParamsM19(ParamsM13):
    portfolio: PortfolioM19


# M21 option (docs/research/m21.md).

class ExitsM21(Exits):
    # Set: after each decision close, the picks are followed as held from that close (adjusted closes, target weights,
    # gold and other fixed symbols left out). At the first close where that value is at or below (1 - this) x its highest
    # close since the decision, every pick is sold at the next open; the cash waits for the next decision date.
    book_stop_frac: float | None

    @model_validator(mode="after")
    def _book(self) -> ExitsM21:
        if self.book_stop_frac is not None and not 0.0 < self.book_stop_frac < 1.0:
            raise ValueError("book_stop_frac must be between 0 and 1")
        return self


class ParamsM21(ParamsM19):
    exits: ExitsM21


# M22 option (docs/research/m22.md).

class PortfolioM22(PortfolioM19):
    # Set: a fixed symbol is held at a decision date only if its adjusted close is above its close this many sessions
    # (rows) earlier; otherwise its weight goes to the picks (Moskowitz, Ooi & Pedersen 2012, time-series momentum).
    fixed_trend_sessions: int | None

    @model_validator(mode="after")
    def _trend(self) -> PortfolioM22:
        if self.fixed_trend_sessions is not None and self.fixed_trend_sessions < 1:
            raise ValueError("fixed_trend_sessions must be at least 1")
        return self


class ParamsM22(ParamsM21):
    portfolio: PortfolioM22
