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


# M27 option (docs/research/m27.md).

class Rotation(Strict):
    # At each decision date and for each lookback, the shadow book (this strategy without rotation, at full investment
    # from the panel's first session) and each symbol in `assets` are scored by their return over that many sessions; the
    # best `top_k` get 1 / top_k each. The shares are averaged over the lookbacks (Faber 2007; Antonacci 2014; Keller).
    assets: list[str]
    lookbacks_sessions: list[int]
    top_k: int
    cash_floor: bool              # a winner whose return is not above 0 gets its share as cash (absolute momentum)

    @model_validator(mode="after")
    def _rotation(self) -> Rotation:
        if not self.assets or len(set(self.assets)) != len(self.assets):
            raise ValueError("rotation.assets must be non-empty and distinct")
        if not self.lookbacks_sessions or any(n < 1 for n in self.lookbacks_sessions):
            raise ValueError("rotation.lookbacks_sessions must be non-empty and at least 1")
        if not 1 <= self.top_k <= len(self.assets) + 1:
            raise ValueError("rotation.top_k must be between 1 and the number of candidates")
        return self


class PortfolioM27(PortfolioM22):
    rotation: Rotation | None

    @model_validator(mode="after")
    def _alone(self) -> PortfolioM27:
        if self.rotation is not None and self.fixed_weights:
            raise ValueError("fixed_weights must be empty when rotation is set")
        return self


class ParamsM27(ParamsM22):
    portfolio: PortfolioM27


# M29 option (docs/research/m29.md).

class RankingM29(RankingM12):
    # low_vol: rank by the stdev of daily log returns over lookback - skip sessions ending `skip_sessions` before the
    # decision date, lowest first (Blitz & van Vliet 2007). score: the usual ranking.
    # htp (M30, docs/research/m30.md): log(highest adj_close from `lookback_sessions` to `skip_sessions` before the
    # decision date / adj_close `lookback_sessions` before), divided by that vol under return_over_vol (Büsing,
    # Mohrschladt & Siedhoff 2024).
    order: Literal["score", "low_vol", "htp"]

    @model_validator(mode="after")
    def _low_vol(self) -> RankingM29:
        if self.order != "score":
            if self.order == "low_vol" and self.score != "return_over_vol":
                raise ValueError("order low_vol needs score return_over_vol")
            on = [k for k in ("second_lookback_sessions", "high_window_sessions", "residual_beta_sessions",
                              "frog_candidates_per_slot", "max_filter_frac") if getattr(self, k) is not None]
            if on:
                raise ValueError(f"order {self.order} takes no other ranking option: {', '.join(on)}")
        return self


class ParamsM29(ParamsM27):
    ranking: RankingM29


# M32 option (docs/research/m32.md).

class VolStates(Strict):
    # Conditional volatility targeting (Bongaerts, Kang & van Dijk 2020) with no leverage: at a decision date where the
    # shadow book's volatility over the last `vol_sessions` sessions is at or above the `high_quantile` quantile of its
    # values at all earlier decision dates (and this one), the picks are scaled by min(1, long-run vol / that vol).
    vol_sessions: int
    high_quantile: float
    min_history_months: int

    @model_validator(mode="after")
    def _states(self) -> VolStates:
        if self.vol_sessions < 2 or not 0.0 < self.high_quantile < 1.0 or self.min_history_months < 1:
            raise ValueError("vol_states: vol_sessions >= 2, 0 < high_quantile < 1, min_history_months >= 1")
        return self


class PortfolioM32(PortfolioM27):
    vol_states: VolStates | None

    @model_validator(mode="after")
    def _vol_states(self) -> PortfolioM32:
        if self.vol_states is not None and (self.rotation is not None or not self.resize_held):
            raise ValueError("vol_states needs rotation null and resize_held true")
        return self


class ParamsM32(ParamsM29):
    portfolio: PortfolioM32


# M40 option (docs/research/m40.md).

class UniverseM40(UniverseM13):
    # Set: at each decision date, drop this share (rounded up) of the otherwise eligible names with the lowest delivery
    # share over the momentum formation span (sum of deliverable quantity / sum of volume over the sessions with a
    # delivery record, from `lookback_sessions` to `skip_sessions` ago). Names with no delivery record there are not
    # eligible. Needs a dataset with `deliv_qty`.
    delivery_drop_frac: float | None

    @model_validator(mode="after")
    def _delivery(self) -> UniverseM40:
        if self.delivery_drop_frac is not None and not 0.0 < self.delivery_drop_frac < 1.0:
            raise ValueError("delivery_drop_frac must be in (0, 1)")
        return self


class ParamsM40(ParamsM32):
    universe: UniverseM40


# M44 option (docs/research/m44.md).

class UniverseM44(UniverseM40):
    # Set: a name is not eligible at a decision date if two consecutive bars within its last `lookback_sessions` rows
    # are more than this many calendar days apart (windows count rows, so a trading gap stretches them over years).
    max_gap_days: int | None

    @model_validator(mode="after")
    def _gap(self) -> UniverseM44:
        if self.max_gap_days is not None and self.max_gap_days < 1:
            raise ValueError("max_gap_days must be at least 1")
        return self


class ParamsM44(ParamsM40):
    universe: UniverseM44
