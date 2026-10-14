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


# M46 option (docs/research/m46.md).

class ScheduleM46(Schedule):
    # Decide only at month-ends with month % every_months == phase_month; 1 and 0 = every month.
    every_months: int
    phase_month: int

    @model_validator(mode="after")
    def _every(self) -> ScheduleM46:
        if self.every_months < 1:
            raise ValueError("every_months must be at least 1")
        if not 0 <= self.phase_month < self.every_months:
            raise ValueError("phase_month must be in [0, every_months)")
        return self


class ParamsM46(ParamsM40):
    schedule: ScheduleM46


# M53 option (docs/research/m53.md).

class AbnormalDelivery(Strict):
    # ratio = mean deliv_qty over the last `recent_sessions` rows up to the decision date / mean over the
    # `base_sessions` rows before those (missing records count as 0); a zero base is not eligible. After the
    # delivery-share drop, the `drop_frac` share (rounded up) of the remaining names with the lowest ratio is dropped.
    recent_sessions: int
    base_sessions: int
    drop_frac: float

    @model_validator(mode="after")
    def _abnormal(self) -> AbnormalDelivery:
        if self.recent_sessions < 1 or self.base_sessions < 1:
            raise ValueError("abnormal_delivery: recent_sessions and base_sessions must be at least 1")
        if not 0.0 < self.drop_frac < 1.0:
            raise ValueError("abnormal_delivery.drop_frac must be in (0, 1)")
        return self


class UniverseM53(UniverseM44):
    abnormal_delivery: AbnormalDelivery | None

    @model_validator(mode="after")
    def _needs_delivery(self) -> UniverseM53:
        if self.abnormal_delivery is not None and self.delivery_drop_frac is None:
            raise ValueError("abnormal_delivery needs delivery_drop_frac (the delivery columns)")
        return self


class ParamsM53(ParamsM44):
    universe: UniverseM53


# M55 option (docs/research/m55.md).

class RankingM55(RankingM29):
    # total: momentum from adj_close as before. intraday: exp(sum of log(adj_close / adj_open)) - 1 over the same
    # `lookback - skip` rows; overnight: the same with log(adj_open / previous adj_close). The vol is unchanged.
    return_part: Literal["total", "intraday", "overnight"]

    @model_validator(mode="after")
    def _part(self) -> RankingM55:
        if self.return_part != "total":
            on = [k for k in ("second_lookback_sessions", "high_window_sessions", "residual_beta_sessions",
                              "frog_candidates_per_slot") if getattr(self, k) is not None]
            if on or self.order != "score":
                raise ValueError(f"return_part {self.return_part} needs order score and none of: {', '.join(on) or 'order'}")
        return self


class ParamsM55(ParamsM53):
    ranking: RankingM55


# M57 option (docs/research/m57.md).

class ScheduleM57(Schedule):
    # Null: month-ends as before. Otherwise decide on the sessions of [start, end] whose index from the period's first
    # session is phase_session mod every_sessions; decision_offset_sessions must then be 0.
    every_sessions: int | None
    phase_session: int

    @model_validator(mode="after")
    def _every(self) -> ScheduleM57:
        if self.every_sessions is None:
            if self.phase_session != 0:
                raise ValueError("phase_session needs every_sessions")
        elif self.every_sessions < 1 or not 0 <= self.phase_session < self.every_sessions:
            raise ValueError("every_sessions must be >= 1 and phase_session in [0, every_sessions)")
        elif self.decision_offset_sessions != 0:
            raise ValueError("every_sessions needs decision_offset_sessions 0")
        return self


class ParamsM57(ParamsM55):
    schedule: ScheduleM57


# M75 option (docs/research/m75.md).

class ExitsM75(ExitsM21):
    # Set: the proceeds of stop-loss sales buy this symbol at the same open instead of waiting in cash; the next rebalance
    # trims it back to its target. It must be a fixed-weight symbol, and it is never stopped itself.
    stop_proceeds_to: str | None

    @model_validator(mode="after")
    def _to(self) -> ExitsM75:
        if self.stop_proceeds_to is not None and self.stop_loss_frac is None:
            raise ValueError("stop_proceeds_to needs stop_loss_frac")
        return self


class ParamsM75(ParamsM57):
    exits: ExitsM75

    @model_validator(mode="after")
    def _park(self) -> ParamsM75:
        to = self.exits.stop_proceeds_to
        if to is not None and to not in self.portfolio.fixed_weights:
            raise ValueError(f"stop_proceeds_to {to} must be in portfolio.fixed_weights")
        return self


# M76 options (docs/research/m76.md).

class ExitsM76(ExitsM75):
    # True: the stop reference ratchets up to the highest close since the last rebalance (a trailing stop).
    stop_trailing: bool
    # Set (both): a name's stop is max(stop_loss_frac, stop_vol_mult x the std of its daily close returns over the
    # stop_vol_sessions sessions up to the decision close); volatile names get a wider stop, none a tighter one.
    stop_vol_sessions: int | None
    stop_vol_mult: float | None

    @model_validator(mode="after")
    def _m76(self) -> ExitsM76:
        if (self.stop_vol_sessions is None) != (self.stop_vol_mult is None):
            raise ValueError("stop_vol_sessions and stop_vol_mult go together")
        if (self.stop_trailing or self.stop_vol_sessions is not None) and self.stop_loss_frac is None:
            raise ValueError("stop_trailing and stop_vol_* need stop_loss_frac")
        if self.stop_vol_sessions is not None and (self.stop_vol_sessions < 2 or self.stop_vol_mult <= 0):
            raise ValueError("stop_vol_sessions must be >= 2 and stop_vol_mult > 0")
        return self


class ParamsM76(ParamsM75):
    exits: ExitsM76


# M79 option (docs/research/m79.md).

class ExitsM79(ExitsM76):
    # Set (both): a name's stop fires only while this symbol also closes at or below (1 - stop_market_frac) x its open at
    # the last rebalance session: stop in a falling market, hold through a dip in a rising one.
    stop_market_symbol: str | None
    stop_market_frac: float | None

    @model_validator(mode="after")
    def _m79(self) -> ExitsM79:
        if (self.stop_market_symbol is None) != (self.stop_market_frac is None):
            raise ValueError("stop_market_symbol and stop_market_frac go together")
        if self.stop_market_symbol is not None and self.stop_loss_frac is None:
            raise ValueError("stop_market_* needs stop_loss_frac")
        if self.stop_market_frac is not None and not 0.0 <= self.stop_market_frac < 1.0:
            raise ValueError("stop_market_frac must be in [0, 1)")
        return self


class ParamsM79(ParamsM76):
    exits: ExitsM79


# M81 option (docs/research/m81.md).

class ExitsM81(ExitsM79):
    # True: a stop's proceeds buy the names still held, pro rata to their value, at the same open (instead of cash).
    stop_respread: bool

    @model_validator(mode="after")
    def _m81(self) -> ExitsM81:
        if self.stop_respread and self.stop_loss_frac is None:
            raise ValueError("stop_respread needs stop_loss_frac")
        if self.stop_respread and self.stop_proceeds_to is not None:
            raise ValueError("stop_respread and stop_proceeds_to are exclusive")
        return self


class ParamsM81(ParamsM79):
    exits: ExitsM81


# M82 option (docs/research/m82.md).

class ExitsM82(ExitsM81):
    # True: a stopped name that closes back at or above its stop reference before the next rebalance is bought back at
    # the next open with up to its stop's proceeds.
    stop_reentry: bool

    @model_validator(mode="after")
    def _m82(self) -> ExitsM82:
        if self.stop_reentry and (self.stop_loss_frac is None or self.stop_proceeds_to is not None
                                  or self.stop_respread or self.stop_trailing):
            raise ValueError("stop_reentry needs a plain stop_loss_frac")
        return self


class ParamsM82(ParamsM81):
    exits: ExitsM82


# M89 option (docs/research/m89.md).

class RegimeM89(Regime):
    # Null: on a risk-off decision date the uninvested share stays in cash. Otherwise it buys this symbol.
    risk_off_symbol: str | None

    @model_validator(mode="after")
    def _m89(self) -> RegimeM89:
        if self.risk_off_symbol is not None and not self.enabled:
            raise ValueError("risk_off_symbol needs the regime enabled")
        return self


class ParamsM89(ParamsM82):
    regime: RegimeM89


# M97 options (docs/research/m97.md).

class RegimeM97(RegimeM89):
    # Empty: one benchmark. Otherwise each listed symbol is a further benchmark with the same moving average, and the
    # invested share is graded: with a fraction f of all benchmarks at or above their averages, gross is
    # f + (1 - f) * risk_off_gross.
    extra_benchmark_symbols: list[str]

    @model_validator(mode="after")
    def _m97(self) -> RegimeM97:
        if self.extra_benchmark_symbols and not self.enabled:
            raise ValueError("extra_benchmark_symbols needs the regime enabled")
        if len(set([self.benchmark_symbol, *self.extra_benchmark_symbols])) != 1 + len(self.extra_benchmark_symbols):
            raise ValueError("regime benchmarks must be distinct")
        return self


class ParamsM97(ParamsM89):
    regime: RegimeM97


# M99 options (docs/research/m99.md).

BREADTH = "UNIVERSE"  # benchmark_symbol value that selects the breadth signal


class RegimeM99(RegimeM97):
    # Null: the benchmark signal. Otherwise benchmark_symbol must be "UNIVERSE" and the signal is breadth: risk-on when
    # at least this fraction of the universe's stocks (series, price, liquidity and fund rules of the ranking) close at
    # or above their own sma_sessions average.
    breadth_min_frac: float | None

    @model_validator(mode="after")
    def _m99(self) -> RegimeM99:
        if (self.breadth_min_frac is not None) != (self.benchmark_symbol == BREADTH):
            raise ValueError(f"breadth_min_frac and benchmark_symbol {BREADTH} go together")
        if self.breadth_min_frac is not None and not 0.0 < self.breadth_min_frac < 1.0:
            raise ValueError("breadth_min_frac must be in (0, 1)")
        return self


class ParamsM99(ParamsM97):
    regime: RegimeM99


# M103 options (docs/research/m103.md).


class RegimeM103(RegimeM99):
    # Null: the plain filter. Otherwise a band around the average (Brock, Lakonishok & LeBaron 1992): at each decision
    # date the state turns off only below average x (1 - band) and back on only above average x (1 + band); in between
    # it keeps the previous decision date's state. The first decision date uses the plain rule.
    band_frac: float | None

    @model_validator(mode="after")
    def _m103(self) -> RegimeM103:
        if self.band_frac is not None:
            if not self.enabled or self.extra_benchmark_symbols or self.breadth_min_frac is not None:
                raise ValueError("band_frac needs the plain single-benchmark regime")
            if not 0.0 < self.band_frac < 0.5:
                raise ValueError("band_frac must be in (0, 0.5)")
        return self


class ParamsM103(ParamsM99):
    regime: RegimeM103


# M110 option (docs/research/m110.md).


class PortfolioM110(PortfolioM32):
    # Null: off. Set: a held name the hold buffer would drop is kept while it has been held (calendar days since the
    # decision that first picked it) at least tax_hold_from_days and less than tax_hold_until_days, its adjusted close is
    # above the one at that decision, and its rank is below tax_hold_rank_max; it is sold at the first decision from
    # tax_hold_until_days on, so the sale is a long-term gain. It keeps its slot.
    tax_hold_from_days: int | None
    tax_hold_until_days: int | None
    tax_hold_rank_max: int | None

    @model_validator(mode="after")
    def _m110(self) -> PortfolioM110:
        on = [self.tax_hold_from_days, self.tax_hold_until_days, self.tax_hold_rank_max]
        if any(v is None for v in on) and any(v is not None for v in on):
            raise ValueError("tax_hold_* are all null or all set")
        if self.tax_hold_from_days is not None:
            assert self.tax_hold_until_days is not None and self.tax_hold_rank_max is not None
            if not 0 < self.tax_hold_from_days < self.tax_hold_until_days:
                raise ValueError("tax_hold_from_days must be in (0, tax_hold_until_days)")
            if self.tax_hold_rank_max < self.hold_rank_max:
                raise ValueError("tax_hold_rank_max must be at least hold_rank_max")
            if self.rotation is not None or self.vol_states is not None or self.max_per_sector is not None:
                raise ValueError("tax_hold_* needs rotation, vol_states and max_per_sector null")
        return self


class ParamsM110(ParamsM103):
    portfolio: PortfolioM110


# M111 option (docs/research/m111.md).


class Insider(Strict):
    raw_dir: str                 # relative to the project root
    categories: list[str]        # PIT person categories that count as insiders
    lookback_days: int           # calendar days of broadcasts before a decision
    # nosell: a name not held is not bought if its net insider value is below 0. buyfirst: new buys first take names
    # with net value above 0 ranked under rank_max, then the rest in rank order.
    rule: Literal["nosell", "buyfirst"]
    rank_max: int | None         # buyfirst only

    @model_validator(mode="after")
    def _insider(self) -> Insider:
        if self.lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if (self.rule == "buyfirst") != (self.rank_max is not None):
            raise ValueError("rank_max is set exactly when rule is buyfirst")
        return self


class ParamsM111(ParamsM110):
    insider: Insider | None

    @model_validator(mode="after")
    def _m111(self) -> ParamsM111:
        if self.insider is not None and self.insider.rank_max is not None and self.insider.rank_max < self.portfolio.top_n:
            raise ValueError("insider.rank_max must be at least top_n")
        if self.insider is not None and self.portfolio.max_per_sector is not None:
            raise ValueError("insider needs max_per_sector null")
        return self


# M114 option (docs/research/m114.md).


class Results(Strict):
    raw_dir: str                 # NSE board-meeting announcements, relative to the project root
    benchmark_symbol: str        # the reaction is the stock's return minus this symbol's
    lookback_days: int           # use the latest results meeting held this many calendar days before a decision
    # noneg: a name not held is not bought if its reaction is below 0. posfirst: new buys first take names with a
    # reaction above 0 ranked under rank_max, then the rest in rank order.
    rule: Literal["noneg", "posfirst"]
    rank_max: int | None         # posfirst only

    @model_validator(mode="after")
    def _results(self) -> Results:
        if self.lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if (self.rule == "posfirst") != (self.rank_max is not None):
            raise ValueError("rank_max is set exactly when rule is posfirst")
        return self


class ParamsM114(ParamsM111):
    results: Results | None

    @model_validator(mode="after")
    def _m114(self) -> ParamsM114:
        if self.results is not None and self.insider is not None:
            raise ValueError("results and insider are exclusive")
        if self.results is not None and self.results.rank_max is not None and self.results.rank_max < self.portfolio.top_n:
            raise ValueError("results.rank_max must be at least top_n")
        if self.results is not None and self.portfolio.max_per_sector is not None:
            raise ValueError("results needs max_per_sector null")
        return self


# M116 option (docs/research/m116.md).


class Deals(Strict):
    raw_dirs: list[str]          # bulk and block deal folders, relative to the project root
    lookback_days: int           # calendar days of deals before a decision
    # nosell: a name not held is not bought if its net deal value is below 0. buyfirst: new buys first take names with
    # net value above 0 ranked under rank_max, then the rest in rank order.
    rule: Literal["nosell", "buyfirst"]
    rank_max: int | None         # buyfirst only

    @model_validator(mode="after")
    def _deals(self) -> Deals:
        if self.lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if (self.rule == "buyfirst") != (self.rank_max is not None):
            raise ValueError("rank_max is set exactly when rule is buyfirst")
        return self


class ParamsM116(ParamsM114):
    deals: Deals | None

    @model_validator(mode="after")
    def _m116(self) -> ParamsM116:
        if self.deals is not None and (self.insider is not None or self.results is not None):
            raise ValueError("deals, results and insider are exclusive")
        if self.deals is not None and self.deals.rank_max is not None and self.deals.rank_max < self.portfolio.top_n:
            raise ValueError("deals.rank_max must be at least top_n")
        if self.deals is not None and self.portfolio.max_per_sector is not None:
            raise ValueError("deals needs max_per_sector null")
        return self


# M117 option (docs/research/m117.md).


class RegimeM117(RegimeM103):
    # Empty: off. Otherwise a decision dated in one of these calendar months is risk-off whatever the benchmark says
    # (Bouman & Jacobsen 2002, "sell in May": decisions dated April-September hold May-October).
    risk_off_months: list[int]

    @model_validator(mode="after")
    def _m117(self) -> RegimeM117:
        if self.risk_off_months:
            if not self.enabled:
                raise ValueError("risk_off_months needs the regime enabled")
            if len(set(self.risk_off_months)) != len(self.risk_off_months) or not all(1 <= m <= 12 for m in self.risk_off_months):
                raise ValueError("risk_off_months must be distinct months 1-12")
        return self


class ParamsM117(ParamsM116):
    regime: RegimeM117


# M118 option (docs/research/m118.md).


class MarketSignal(Strict):
    # A second risk-off condition: a decision is risk-off when the benchmark filter says so or this signal is off.
    kind: Literal["vrp", "pcr", "fii_futures"]
    raw_dir: str                  # under the repo root: nse_india_vix (vrp), nse_fo_bhav (pcr), nse_participant_oi (fii_futures)
    option_symbol: str | None     # pcr: the index whose options give the put-call ratio
    rv_symbol: str | None         # vrp: realised variance from this symbol's adj_close
    rv_sessions: int | None       # vrp
    window_sessions: int | None   # pcr, fii_futures: off when the value ranks below min_pct of its last this many values
    min_pct: float | None

    @model_validator(mode="after")
    def _m118(self) -> MarketSignal:
        vrp = (self.rv_symbol, self.rv_sessions)
        ranked = (self.window_sessions, self.min_pct)
        if self.kind == "vrp":
            if None in vrp or ranked != (None, None) or self.option_symbol is not None:
                raise ValueError("vrp takes rv_symbol and rv_sessions only")
            assert self.rv_sessions is not None
            if self.rv_sessions < 2:
                raise ValueError("rv_sessions must be at least 2")
        else:
            if None in ranked or vrp != (None, None) or (self.option_symbol is None) != (self.kind != "pcr"):
                raise ValueError(f"{self.kind} takes window_sessions and min_pct (and option_symbol for pcr) only")
            assert self.window_sessions is not None and self.min_pct is not None
            if self.window_sessions < 2 or not 0.0 < self.min_pct < 1.0:
                raise ValueError("window_sessions must be at least 2 and min_pct in (0, 1)")
        return self


class RegimeM118(RegimeM117):
    market_signal: MarketSignal | None

    @model_validator(mode="after")
    def _m118(self) -> RegimeM118:
        if self.market_signal is not None and not self.enabled:
            raise ValueError("market_signal needs the regime enabled")
        return self


class ParamsM118(ParamsM117):
    regime: RegimeM118
