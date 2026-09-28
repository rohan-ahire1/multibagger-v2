"""The shared back half of a strategy run: signals in, a scored and gated RunResult out.

A strategy produces signals (symbol, signal_date, entry_ref, stop, size_mult). This module loads the bars and the sector
map, runs the engine, applies the data gate, and computes the metrics. Strategies do not touch the engine directly.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import polars as pl

from mb.config.loader import Resolved
from mb.data import datasets
from mb.engine.config import EngineConfig
from mb.engine.gate import enforce_data_gate
from mb.engine.simulate import SimResult, simulate
from mb.evaluation.metrics import equity_metrics, exposure_metrics, trade_metrics
from mb.runs.record import RunResult

JUMPS_FILE = "unexplained_jumps.parquet"


def load_sectors(root: Path, cfg: Resolved) -> dict[str, str]:
    m = pl.read_csv(root / cfg.market.sector_map_file)
    return dict(zip(m["Symbol"].to_list(), m["Industry"].to_list(), strict=True))


def load_bars(root: Path, cfg: Resolved, eng: EngineConfig) -> pl.DataFrame:
    """Adjusted bars from period.start to period.end plus the settle window, under the names the engine expects."""
    path = datasets.dataset_path(root, cfg.strategy.dataset) / datasets.PANEL_FILE
    end = cfg.strategy.period.end + timedelta(days=eng.settle_calendar_days)
    return (pl.scan_parquet(path)
            .filter(pl.col("date").is_between(cfg.strategy.period.start, end))
            .select("date", "symbol", pl.col("adj_open").alias("open"), pl.col("adj_high").alias("high"),
                    pl.col("adj_low").alias("low"), pl.col("adj_close").alias("close"))
            .collect())


def evaluate(cfg: Resolved, root: Path, eng: EngineConfig, signals: pl.DataFrame, bars: pl.DataFrame) -> tuple[SimResult, RunResult]:
    period = cfg.strategy.period
    res = simulate(signals, bars, load_sectors(root, cfg), eng, cfg.market)
    jumps = pl.read_parquet(datasets.dataset_path(root, cfg.strategy.dataset) / JUMPS_FILE)
    enforce_data_gate(res.trades, jumps)
    metrics = {
        "strategy": {
            **equity_metrics(res.equity, period.start, period.end),
            **exposure_metrics(res.equity, res.trades, period.start, period.end),
            **trade_metrics(res.trades, period.start, period.end),
            "signals": signals.height,
            "signals_not_filled_or_refused": res.skipped.height,
        },
        "baselines": {},
    }
    return res, RunResult(metrics=metrics, trades=res.trades, equity=res.equity)
