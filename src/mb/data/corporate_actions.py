"""Load the corporate-action feed merged with curated overrides."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from mb.config.models import CorporateActionsSource

SHARE_ACTIONS = ("split", "bonus", "face_value", "bonus_split")
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


def load_actions(cfg: CorporateActionsSource, root: Path, max_date: date) -> pl.DataFrame:
    """Feed + overrides, share actions and dividends only, ex-dated on or before `max_date`.

    An override states the total multiplier for its symbol-date, so it replaces every feed row there.
    Actions after the last price date belong to a later build.
    """
    feed = pl.read_parquet(root / cfg.raw_file)
    overrides = load_overrides(root / cfg.overrides_file, cfg.applied_override_sources)
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
