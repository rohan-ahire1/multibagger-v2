"""Symbol-keyed back-adjustment matched to observed price jumps.

Ported from v1 `data_sources/sim_prices.py` and `adjustment.py`. Each share action is matched to
the session where the price actually jumped, within a few sessions of the listed ex-date.
Unmatched actions and unexplained jumps are reported, not guessed.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from datetime import date

import polars as pl

from mb.config.models import AdjustmentConfig
from mb.data.corporate_actions import PRICE_ONLY_ACTIONS, SHARE_ACTIONS

_ANCHOR_DATE = date(1990, 1, 1)


def _fv_multiplier(row: dict) -> float | None:
    old, new = row.get("old_face_value"), row.get("new_face_value")
    return float(new) / float(old) if old and new and old > 0 else None


def _bonus_multiplier(row: dict) -> float | None:
    num, den = row.get("ratio_num"), row.get("ratio_den")  # "Bonus a:b": a new per b held
    if num is not None and den:
        a, b = float(num), float(den)
        if a + b > 0:
            return b / (a + b)
    return None


def event_price_multiplier(row: dict) -> float | None:
    """Price multiplier for one share action, applied to all dates before the ex-date."""
    explicit = row.get("adjustment_factor")
    if explicit is not None and float(explicit) > 0:
        return float(explicit)
    action = (row.get("action_type") or "").lower()
    if action in {"split", "face_value"}:
        m = _fv_multiplier(row)
        if m is not None:
            return m
        num, den = row.get("ratio_num"), row.get("ratio_den")
        if num and den and num > 0:
            return float(den) / float(num)
        return None
    if action == "bonus":
        return _bonus_multiplier(row)
    if action == "bonus_split":
        fv, bon = _fv_multiplier(row), _bonus_multiplier(row)
        if fv is None and bon is None:
            return None
        return (fv or 1.0) * (bon or 1.0)
    return None


def expected_share_events(actions: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """One expected multiplier per (symbol, listed date), plus the actions with no derivable multiplier.

    Precedence on one symbol-date: rows with an explicit `adjustment_factor` win; else a combined
    `bonus_split` row wins over separate legs; else the legs multiply.
    """
    rows: list[dict] = []
    unusable: list[dict] = []
    share = actions.filter(pl.col("action_type").is_in(SHARE_ACTIONS))
    for (symbol, ex_date), group in share.group_by(["symbol", "ex_date"], maintain_order=True):
        records = group.to_dicts()
        explicit = [r for r in records if (r.get("adjustment_factor") or 0) > 0]
        combined = [r for r in records if r["action_type"] == "bonus_split"]
        chosen = explicit or combined[:1] or records
        mult: float | None = 1.0
        for record in chosen:
            m = event_price_multiplier(record)
            if m is None or m <= 0:
                unusable.append({"symbol": symbol, "ex_date": ex_date, "action_type": record["action_type"],
                                 "reason": "no multiplier derivable"})
                mult = None
                break
            mult *= m
        if mult is None or math.isclose(mult, 1.0):
            continue
        rows.append({"symbol": symbol, "ex_date": ex_date, "expected": mult,
                     "sources": ",".join(sorted({str(r.get("source") or "") for r in chosen})),
                     "adjusts_volume": all(r["action_type"] not in PRICE_ONLY_ACTIONS for r in chosen)})
    events = pl.DataFrame(rows, schema={"symbol": pl.Utf8, "ex_date": pl.Date, "expected": pl.Float64,
                                        "sources": pl.Utf8, "adjusts_volume": pl.Boolean})
    bad = pl.DataFrame(unusable, schema={"symbol": pl.Utf8, "ex_date": pl.Date, "action_type": pl.Utf8,
                                         "reason": pl.Utf8})
    return events.sort(["symbol", "ex_date"]), bad.sort(["symbol", "ex_date", "action_type"])


def _gap_ratios(prices: pl.DataFrame) -> dict[str, tuple[list[date], list[float | None]]]:
    """Per symbol: session dates and the open / previous-close ratio into each session."""
    frame = (
        prices.select("symbol", "date", "open", "close")
        .sort(["symbol", "date"])
        .with_columns(pl.col("close").shift(1).over("symbol").alias("prev_close"))
        .with_columns(
            pl.when((pl.col("open") > 0) & (pl.col("prev_close") > 0)).then(pl.col("open") / pl.col("prev_close"))
            .when(pl.col("prev_close") > 0).then(pl.col("close") / pl.col("prev_close"))
            .alias("gap")
        )
    )
    return {p["symbol"][0]: (p["date"].to_list(), p["gap"].to_list())
            for p in frame.partition_by("symbol", maintain_order=True)}


def match_share_events(prices: pl.DataFrame, events: pl.DataFrame, cfg: AdjustmentConfig) -> pl.DataFrame:
    """Locate each expected share event on the session where it shows in prices.

    status: matched | applied_small (too small to verify; applied on listed date) |
    duplicate (another event already explains that jump) | unmatched | no_prices.
    Only matched and applied_small are applied.
    """
    series = _gap_ratios(prices)
    tolerance = math.log(cfg.match_tolerance)
    rows: list[dict] = []
    for event in events.iter_rows(named=True):
        base = {**event, "effective_date": None, "observed": None, "offset": None, "_err": None}
        found = series.get(event["symbol"])
        if found is None:
            rows.append({**base, "status": "no_prices"})
            continue
        dates, gaps = found
        idx = bisect_left(dates, event["ex_date"])
        if idx >= len(dates):
            rows.append({**base, "status": "no_prices"})
            continue
        if abs(math.log(event["expected"])) < math.log(cfg.min_detectable):
            rows.append({**base, "effective_date": dates[idx], "offset": 0, "status": "applied_small"})
            continue
        best: tuple[float, int] | None = None
        for j in range(max(1, idx - cfg.match_window_sessions), min(len(dates), idx + cfg.match_window_sessions + 1)):
            gap = gaps[j]
            if gap is None or gap <= 0:
                continue
            err = abs(math.log(gap) - math.log(event["expected"]))
            if best is None or err < best[0]:
                best = (err, j)
        if best is None or best[0] > tolerance:
            rows.append({**base, "observed": gaps[best[1]] if best else None, "status": "unmatched"})
            continue
        j = best[1]
        rows.append({**base, "effective_date": dates[j], "observed": gaps[j], "offset": j - idx,
                     "status": "matched", "_err": best[0]})
    schema = {"symbol": pl.Utf8, "ex_date": pl.Date, "expected": pl.Float64, "sources": pl.Utf8,
              "adjusts_volume": pl.Boolean, "effective_date": pl.Date, "observed": pl.Float64, "offset": pl.Int64, "status": pl.Utf8,
              "_err": pl.Float64}
    matched = pl.DataFrame(rows, schema=schema)
    # Two listed events explaining the same observed jump: keep the closer fit.
    ranked = matched.with_columns(pl.col("_err").rank("ordinal").over(["symbol", "effective_date"]).alias("_rank"))
    return (
        ranked.with_columns(
            pl.when((pl.col("status") == "matched") & (pl.col("_rank") > 1)).then(pl.lit("duplicate"))
            .otherwise(pl.col("status")).alias("status")
        )
        .drop("_err", "_rank")
        .sort(["symbol", "ex_date"])
    )


def dividend_steps(prices: pl.DataFrame, actions: pl.DataFrame, cfg: AdjustmentConfig) -> pl.DataFrame:
    """Dividend multipliers on the first session on or after each ex-date.

    m = 1 - D / prev_close, prev_close being the last close strictly before the ex-date.
    Dividends above `dividend_max_price_fraction` of the price are dropped as implausible. A row with an explicit
    `adjustment_factor` (a reviewed override) is used as given, cap included.
    """
    schema = {"symbol": pl.Utf8, "effective_date": pl.Date, "mult": pl.Float64}
    if "adjustment_factor" not in actions.columns:
        actions = actions.with_columns(pl.lit(None, dtype=pl.Float64).alias("adjustment_factor"))
    is_div = pl.col("action_type") == "dividend"
    has_factor = pl.col("adjustment_factor").fill_null(0.0) > 0
    divs = actions.filter(is_div & ~has_factor & (pl.col("dividend_amount") > 0)).select(
        "symbol", "ex_date", "dividend_amount")
    explicit = actions.filter(is_div & has_factor).select("symbol", "ex_date", pl.col("adjustment_factor").cast(pl.Float64)
                                                          .alias("mult"))
    if divs.is_empty() and explicit.is_empty():
        return pl.DataFrame(schema=schema)
    closes = prices.select("symbol", "date", "close").sort(["symbol", "date"])
    explicit = (
        explicit.sort(["symbol", "ex_date"])
        .join_asof(
            closes.select("symbol", pl.col("date").alias("effective_date"), pl.col("date").alias("ex_date")),
            on="ex_date", by="symbol", strategy="forward", check_sortedness=False,
        )
        .filter(pl.col("effective_date").is_not_null())
        .select(list(schema))
    )
    divs = (
        divs.sort(["symbol", "ex_date"])
        .with_columns((pl.col("ex_date") - pl.duration(days=1)).alias("_before"))
        .join_asof(closes.rename({"date": "_before"}), on="_before", by="symbol", strategy="backward",
                   check_sortedness=False)
        .join_asof(
            closes.select("symbol", pl.col("date").alias("effective_date"), pl.col("date").alias("ex_date")),
            on="ex_date", by="symbol", strategy="forward", check_sortedness=False,
        )
        .with_columns((1 - pl.col("dividend_amount") / pl.col("close")).alias("mult"))
        .filter(pl.col("mult").is_between(1.0 - cfg.dividend_max_price_fraction, 1.0, closed="left")
                & pl.col("effective_date").is_not_null())
        .select(list(schema))
    )
    divs = pl.concat([divs, explicit])
    return divs.group_by(["symbol", "effective_date"]).agg(pl.col("mult").product()).sort(["symbol", "effective_date"])


def _factor_steps(events: pl.DataFrame) -> pl.DataFrame:
    """Per-symbol step table: `factor` applies to all dates >= `date`.

    factor(t) = product of every event multiplier with ex_date > t (back-adjustment).
    """
    steps: list[dict] = []
    if not events.is_empty():
        for (symbol,), grp in events.sort(["symbol", "ex_date"]).group_by("symbol", maintain_order=True):
            mults, ex_dates = grp["mult"].to_list(), grp["ex_date"].to_list()
            full = 1.0
            for m in mults:
                full *= m
            steps.append({"symbol": symbol, "date": _ANCHOR_DATE, "factor": full})
            prefix = 1.0
            for ex, m in zip(ex_dates, mults):
                prefix *= m
                steps.append({"symbol": symbol, "date": ex, "factor": full / prefix})
    return pl.DataFrame(steps, schema={"symbol": pl.Utf8, "date": pl.Date, "factor": pl.Float64}).sort(
        ["symbol", "date"])


def _join_factor(bars: pl.DataFrame, steps: pl.DataFrame) -> pl.Series:
    if steps.is_empty():
        return pl.Series("factor", [1.0] * bars.height)
    joined = bars.select("symbol", "date").with_row_index("_i").sort(["symbol", "date"]).join_asof(
        steps, on="date", by="symbol", strategy="backward", check_sortedness=False)
    return joined.sort("_i")["factor"].fill_null(1.0)


def build_research_panel(bars: pl.DataFrame, matches: pl.DataFrame, dividends: pl.DataFrame) -> pl.DataFrame:
    """Canonical bars plus `adj_open..adj_close`, `adj_volume`, `adj_factor`.

    Share events (matched / applied_small) adjust price, and volume unless price-only (rights, demerger); dividends
    adjust price only.
    """
    bars = bars.sort(["symbol", "date"])
    applied = matches.filter(pl.col("status").is_in(["matched", "applied_small"]))
    share = applied.select("symbol", pl.col("effective_date").alias("ex_date"), pl.col("expected").alias("mult"))
    volume = applied.filter(pl.col("adjusts_volume")).select(
        "symbol", pl.col("effective_date").alias("ex_date"), pl.col("expected").alias("mult"))
    div = dividends.select("symbol", pl.col("effective_date").alias("ex_date"), "mult")
    price_factor = _join_factor(bars, _factor_steps(pl.concat([share, div])))
    volume_factor = _join_factor(bars, _factor_steps(volume))
    return bars.with_columns(
        *((pl.col(c) * price_factor).alias(f"adj_{c}") for c in ("open", "high", "low", "close")),
        (pl.col("volume") / volume_factor).round(0).cast(pl.Int64).alias("adj_volume"),
        price_factor.alias("adj_factor"),
    )


def unexplained_jumps(panel: pl.DataFrame, cfg: AdjustmentConfig, verified: pl.DataFrame) -> pl.DataFrame:
    """Session-to-session adjusted-close moves beyond `unexplained_jump` either way, less the verified real moves.

    A verified move that is not in the list is an error: the file would claim something the data does not show.
    """
    j = cfg.unexplained_jump
    jumps = (
        panel.select("symbol", "date", pl.col("adj_close").alias("close"))
        .sort(["symbol", "date"])
        .with_columns((pl.col("close") / pl.col("close").shift(1).over("symbol")).alias("ratio"))
        .filter((pl.col("ratio") > j) | (pl.col("ratio") < 1 / j))
        .select("symbol", "date", "ratio")
    )
    stale = verified.join(jumps, on=["symbol", "date"], how="anti")
    if stale.height:
        raise ValueError(f"verified moves that are not unexplained jumps: {stale.select('symbol', 'date').rows()}")
    return jumps.join(verified.select("symbol", "date"), on=["symbol", "date"], how="anti")
