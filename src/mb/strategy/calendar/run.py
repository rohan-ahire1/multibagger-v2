"""Turn-of-month strategy (M111, docs/research/m111.md): buy one symbol at the close of a fixed session before the
month's end, hold a fixed number of sessions (the engine's `hold_sessions`), sell at that session's close.

Sessions are the panel's trading days. The month's last session is known in advance from the exchange calendar."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from mb.config.loader import Resolved
from mb.data import datasets
from mb.engine.run import evaluate, load_bars
from mb.runs.record import RunResult
from mb.strategy.calendar.params import Params

__all__ = ["Params", "run", "signals"]


def signals(panel: pl.DataFrame, p: Params, start, end) -> pl.DataFrame:
    """One signal a month, dated the session before the entry session; the engine's `close` order fills at the entry
    session's close."""
    if p.engine.entry.order != "close":
        raise ValueError("the calendar strategy needs the engine's `close` order")
    if p.entry_session_from_end < 1:
        raise ValueError("entry_session_from_end must be >= 1")
    schema = {"symbol": pl.String, "signal_date": pl.Date, "entry_ref": pl.Float64, "stop": pl.Float64,
              "size_mult": pl.Float64}
    if not p.trade:
        return pl.DataFrame(schema=schema)
    sessions = (panel.select("date").unique().sort("date")
                .with_columns(pl.col("date").dt.strftime("%Y-%m").alias("ym"))
                .with_columns(pl.int_range(pl.len()).reverse().over("ym").alias("from_end")))  # 0 = last session
    sessions = sessions.with_columns(pl.col("date").shift(1).alias("prev"))
    entry = sessions.filter(pl.col("from_end") == p.entry_session_from_end - 1).drop_nulls("prev")
    px = panel.filter(pl.col("symbol") == p.symbol).select("date", "adj_close")
    if px.is_empty():
        raise ValueError(f"{p.symbol} is not in the panel")
    return (entry.select(pl.col("prev").alias("signal_date"))
            .join(px, left_on="signal_date", right_on="date", how="inner")
            .filter(pl.col("signal_date").is_between(start, end))
            .select(pl.lit(p.symbol).alias("symbol"), "signal_date", pl.col("adj_close").alias("entry_ref"),
                    (pl.col("adj_close") * (1.0 - p.stop_below_ref_pct)).alias("stop"), pl.lit(1.0).alias("size_mult"))
            .cast(schema))


def run(cfg: Resolved, root: Path) -> RunResult:
    p = cfg.params
    assert isinstance(p, Params)
    period = cfg.strategy.period
    panel = (pl.scan_parquet(datasets.dataset_path(root, cfg.strategy.dataset) / datasets.PANEL_FILE)
             .filter(pl.col("date") <= period.end).select("date", "symbol", "adj_close").collect())
    sigs = signals(panel, p, period.start, period.end)
    _, result = evaluate(cfg, root, p.engine, sigs, load_bars(root, cfg, p.engine))
    return result
