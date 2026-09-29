"""Load the corporate-action feed merged with curated overrides."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from mb.config.models import CorporateActionsSource
from mb.data.renames import relabel

SHARE_ACTIONS = ("split", "bonus", "face_value", "bonus_split", "rights", "demerger")
# Adjust price only, never volume, and need an explicit `adjustment_factor` (an override row).
PRICE_ONLY_ACTIONS = ("rights", "demerger")
_OVERRIDE_TYPES = {
    "isin": pl.Utf8, "ratio_num": pl.Float64, "ratio_den": pl.Float64, "old_face_value": pl.Float64,
    "new_face_value": pl.Float64, "dividend_amount": pl.Float64, "source": pl.Utf8,
}
_OVERRIDE_COLUMNS = (
    "symbol", "isin", "ex_date", "action_type", "ratio_num", "ratio_den", "old_face_value",
    "new_face_value", "dividend_amount", "adjustment_factor", "raw_purpose", "source",
)


class OverrideError(ValueError):
    pass


def load_overrides(path: Path, applied_sources: list[str]) -> pl.DataFrame | None:
    """Curated CA rows. Only listed sources are applied; `seed` rows are inert.

    A row with an unrecognised source would be silently ignored, leaving its jump in the panel
    while the file claims it was handled, so that is an error.
    """
    raw = pl.read_csv(path, try_parse_dates=True)
    if raw.is_empty() or "source" not in raw.columns:
        return None
    unknown = sorted(set(raw["source"].drop_nulls().to_list()) - set(applied_sources) - {"seed"})
    if unknown:
        raise OverrideError(f"{path} has rows with unrecognised source(s) {unknown}")
    frame = raw.filter(pl.col("source").is_in(applied_sources))
    if frame.is_empty():
        return None
    frame = frame.with_columns(pl.col("ex_date").cast(pl.Date))
    if "raw_purpose" not in frame.columns:
        src = pl.col("description") if "description" in frame.columns else pl.lit(None, dtype=pl.Utf8)
        frame = frame.with_columns(src.alias("raw_purpose"))
    for col, dtype in _OVERRIDE_TYPES.items():
        expr = pl.col(col).cast(dtype) if col in frame.columns else pl.lit(None, dtype=dtype)
        frame = frame.with_columns(expr.alias(col))
    return frame.select(_OVERRIDE_COLUMNS)


def resymbol_by_isin(feed: pl.DataFrame, bars: pl.DataFrame) -> pl.DataFrame:
    """Move each feed row to the symbol its ISIN traded under on the last session before the ex-date.

    The feed lists an action under the company's current ISIN. When a split or bonus brought a new ISIN, no bars carry
    it before the ex-date, so the row goes to the symbol that ISIN first traded under from the ex-date on.

    Adds `feed_symbol` (the symbol the feed used). A moved row is dropped if the target symbol already lists the same
    action type on that date, so a company listed under both symbols is not adjusted twice.
    """
    listed = (bars.filter(pl.col("security_id").str.starts_with("isin:"))
              .select(pl.col("security_id").str.slice(5).alias("isin"), pl.col("date").alias("_before"),
                      pl.col("symbol").alias("_bar_symbol"))
              .unique().sort("_before"))
    keyed = (feed.with_row_index("_i").with_columns((pl.col("ex_date") - pl.duration(days=1)).alias("_before"))
             .sort("_before")
             .join_asof(listed, on="_before", by="isin", strategy="backward", check_sortedness=False)
             .with_columns(pl.col("ex_date").alias("_from")).sort("_from")
             .join_asof(listed.rename({"_before": "_from", "_bar_symbol": "_new_isin_symbol"}), on="_from", by="isin",
                        strategy="forward", check_sortedness=False)
             .sort("_i")
             .with_columns(pl.col("symbol").alias("feed_symbol"),
                           pl.coalesce("_bar_symbol", "_new_isin_symbol", "symbol").alias("symbol")))
    moved = keyed.filter(pl.col("symbol") != pl.col("feed_symbol"))
    native = keyed.filter(pl.col("symbol") == pl.col("feed_symbol"))
    moved = moved.join(native.select("symbol", "ex_date", "action_type").unique(),
                       on=["symbol", "ex_date", "action_type"], how="anti")
    return pl.concat([native, moved]).sort("_i").drop("_i", "_before", "_bar_symbol", "_from", "_new_isin_symbol")


def load_actions(cfg: CorporateActionsSource, root: Path, max_date: date, bars: pl.DataFrame,
                 links: pl.DataFrame | None = None) -> pl.DataFrame:
    """Feed + overrides, share actions and dividends only, ex-dated on or before `max_date`.

    Feed rows are re-keyed to bar symbols first (when `resymbol_by_isin`); overrides are written against bar symbols.
    Price-only actions come from overrides alone: the feed has no factor for them.
    An override states the total multiplier for its symbol-date, so it replaces every feed row there.
    Actions after the last price date belong to a later build.
    `links` (M14 rename links): overrides written against an old symbol move to its later symbol, as its bars did.
    """
    feed = pl.read_parquet(root / cfg.raw_file).filter(~pl.col("action_type").is_in(PRICE_ONLY_ACTIONS))
    feed = resymbol_by_isin(feed, bars) if cfg.resymbol_by_isin else feed.with_columns(pl.col("symbol").alias("feed_symbol"))
    overrides = load_overrides(root / cfg.overrides_file, cfg.applied_override_sources)
    if overrides is not None and links is not None:
        overrides = relabel(overrides, links, "ex_date")
    if overrides is not None:
        feed = feed.join(overrides.select("symbol", "ex_date").unique(), on=["symbol", "ex_date"], how="anti")
        overrides = overrides.with_columns(
            [pl.col(n).cast(t) for n, t in feed.schema.items() if n in overrides.columns]
        )
        feed = pl.concat([feed, overrides], how="diagonal")
    keep = [*SHARE_ACTIONS, "dividend"]
    return (
        feed.filter(pl.col("action_type").is_in(keep) & (pl.col("ex_date") <= pl.lit(max_date)))
        .sort(["symbol", "ex_date", "action_type", "source"])
    )


def load_verified_moves(path: Path) -> pl.DataFrame:
    """symbol, date, reason, source. Every row needs a reason and a source."""
    frame = pl.read_csv(path, try_parse_dates=True, schema_overrides={"symbol": pl.Utf8, "reason": pl.Utf8,
                                                                       "source": pl.Utf8})
    missing = {"symbol", "date", "reason", "source"} - set(frame.columns)
    if missing:
        raise OverrideError(f"{path} lacks columns {sorted(missing)}")
    if frame.height and (frame["reason"].is_null().any() or frame["source"].is_null().any()):
        raise OverrideError(f"{path}: every verified move needs a reason and a source")
    return frame.select("symbol", pl.col("date").cast(pl.Date), "reason", "source")
