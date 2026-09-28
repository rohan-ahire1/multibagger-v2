"""SEPA strategy runner: panel -> signals -> engine -> metrics."""
from __future__ import annotations

from pathlib import Path

import polars as pl

from mb.config.loader import Resolved
from mb.data import datasets
from mb.engine.run import evaluate, load_bars
from mb.runs.record import RunResult
from mb.strategy.sepa import signals
from mb.strategy.sepa.params import Params

__all__ = ["Params", "run"]


def make_signals(cfg: Resolved, root: Path) -> pl.DataFrame:
    """Signals dated inside the config period. The panel is cut at period.end, so later data cannot leak in."""
    p = cfg.params
    assert isinstance(p, Params)
    period = cfg.strategy.period
    panel = pl.scan_parquet(datasets.dataset_path(root, cfg.strategy.dataset) / datasets.PANEL_FILE)
    panel = panel.filter(pl.col("date") <= period.end).collect()
    return signals.breakout_signals(signals.features(panel, p), p, period.start, period.end)


def run(cfg: Resolved, root: Path) -> RunResult:
    p = cfg.params
    assert isinstance(p, Params)
    sigs = make_signals(cfg, root)
    _, result = evaluate(cfg, root, p.engine, sigs, load_bars(root, cfg, p.engine))
    return result
