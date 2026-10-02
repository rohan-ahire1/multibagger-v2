"""M107 (docs/research/m107.md): the locked window cut from the two final runs, beside both baselines (information).

Run ids come from reports/m107_runs.txt. Run: uv run python notebooks/m107_final.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.evaluation.baselines import buy_and_hold_curve, momentum_curve
from mb.evaluation.metrics import equity_metrics

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "strategies/momentum/configs/m107_final_g25_jr_gap.yaml"
WINDOWS = {"locked 2024-01-01..2026-09-28": (date(2024, 1, 1), date(2026, 9, 28)),
           "locked to TRI end 2024-01-01..2026-03-17": (date(2024, 1, 1), date(2026, 3, 17)),
           "whole 2010-01-04..2026-09-28": (date(2010, 1, 4), date(2026, 9, 28))}

ids = dict(line.split(" run ") for line in (ROOT / "reports/m107_runs.txt").read_text().splitlines() if " run " in line)
cfg = load_strategy_config(CFG, ROOT)
per = cfg.strategy.period
curves = {name: pl.read_parquet(ROOT / f"runs/{rid}/equity.parquet").select("date", "equity").sort("date")
          for name, rid in ids.items()}
panel = datasets.dataset_path(ROOT, cfg.strategy.dataset) / datasets.PANEL_FILE
curves["baseline momentum_12_1"] = momentum_curve(cfg.baselines, cfg.market, panel, per.start, per.end)[0]
curves["baseline nifty500_tri"] = buy_and_hold_curve(ROOT, cfg.baselines)
for w, (a, b) in WINDOWS.items():
    print(w)
    for name, c in curves.items():
        if c["date"].max() < b and name == "baseline nifty500_tri":
            print(f"    {name}: ends {c['date'].max()}, see the TRI window")
            continue
        m = equity_metrics(c, a, b)
        print(f"    {name} ({ids.get(name, '-')}): CAGR {m['cagr'] * 100:.2f}% max DD {m['max_drawdown'] * 100:.2f}% "
              f"Calmar {m['calmar']:.3f}")
