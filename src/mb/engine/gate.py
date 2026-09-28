"""Data gate: a run whose trades were held through an unexplained price jump is refused.

An unexplained jump is a big overnight move in the adjusted series that no split, bonus or demerger explains
(a missed corporate action, a symbol reused by another company). A trade's P&L across one is not real.
"""
from __future__ import annotations

import polars as pl


class DataGateError(RuntimeError):
    pass


def trades_touching_jumps(trades: pl.DataFrame, jumps: pl.DataFrame) -> pl.DataFrame:
    """Filled trades whose holding period contains a jump. A jump on the entry session counts: the fill reflects it."""
    filled = trades.filter(pl.col("entry_date").is_not_null() & pl.col("exit_date").is_not_null())
    if filled.is_empty() or jumps.is_empty():
        return filled.head(0)
    hits = filled.join(jumps.select("symbol", pl.col("date").alias("jump_date"), "ratio"), on="symbol")
    return hits.filter((pl.col("jump_date") >= pl.col("entry_date")) & (pl.col("jump_date") <= pl.col("exit_date")))


def enforce_data_gate(trades: pl.DataFrame, jumps: pl.DataFrame) -> None:
    hits = trades_touching_jumps(trades, jumps)
    if hits.height:
        rows = "; ".join(f"{r['symbol']} {r['entry_date']}..{r['exit_date']} jump {r['jump_date']} x{r['ratio']:.3f}"
                         for r in hits.head(5).iter_rows(named=True))
        raise DataGateError(f"{hits.height} trade(s) held through an unexplained price jump: {rows}")
