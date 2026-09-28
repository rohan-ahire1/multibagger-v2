"""The shared back half of a strategy run: signals in, a scored and gated RunResult out.

A signal strategy produces signals (symbol, signal_date, entry_ref, stop, size_mult). This module loads the bars and the
sector map, runs the engine, applies the data gate, and computes the metrics. Strategies do not touch the engine directly.
A rebalance strategy runs `engine.rebalance.simulate_targets` and hands its equity and holdings to `score`.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import polars as pl

from mb.config.loader import Resolved
from mb.data import datasets
from mb.engine.config import EngineConfig
from mb.engine.gate import enforce_data_gate
from mb.engine.simulate import SimResult, simulate
from mb.evaluation import baselines
from mb.evaluation.metrics import equity_metrics, exposure_metrics, trade_metrics, traded_value
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
    exposure = exposure_metrics(res.equity, traded_value(res.trades, period.start, period.end), period.start, period.end)
    extra = {"signals": signals.height, "signals_not_filled_or_refused": res.skipped.height}
    return res, score(cfg, root, res.equity, res.trades, exposure, extra)


def score(cfg: Resolved, root: Path, equity: pl.DataFrame, trades: pl.DataFrame, exposure: dict[str, Any],
          extra: dict[str, Any]) -> RunResult:
    """Data gate, then metrics for the period and each development fold inside it, then the baselines.

    Every strategy kind ends here. `trades` are the engine's trades or a rebalance strategy's holdings.
    """
    period = cfg.strategy.period
    panel = datasets.dataset_path(root, cfg.strategy.dataset) / datasets.PANEL_FILE
    enforce_data_gate(trades, pl.read_parquet(datasets.dataset_path(root, cfg.strategy.dataset) / JUMPS_FILE))
    folds = {f.name: {**equity_metrics(equity, f.start, f.end), "trades": trade_metrics(trades, f.start, f.end).get("trades")}
             for f in cfg.baselines.folds if f.start >= period.start and f.end <= period.end}
    metrics = {
        "strategy": {**equity_metrics(equity, period.start, period.end), **exposure,
                     **trade_metrics(trades, period.start, period.end), **extra},
        "folds": folds,
        "baselines": baselines.compute(root, cfg.baselines, cfg.market, panel, period.start, period.end),
    }
    return RunResult(metrics=metrics, trades=trades, equity=equity)
