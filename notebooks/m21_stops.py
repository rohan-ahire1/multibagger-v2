"""M21 (docs/research/m21.md): when the book stop fired, and whether the picks recovered by the next decision date.

Run: uv run python notebooks/m21_stops.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.strategy.momentum.params import ParamsM21
from mb.strategy.momentum.targets import targets

ROOT = Path(__file__).resolve().parents[1]
RUNS = {"m21_gold20_bstop10_b2": "20260929-203629-8baafb03", "m21_gold20_bstop15_b2": "20260929-203640-ca4dc10b"}

for name, run in RUNS.items():
    cfg = load_strategy_config(ROOT / f"strategies/momentum/configs/{name}.yaml", ROOT)
    p = cfg.params
    assert isinstance(p, ParamsM21)
    per = cfg.strategy.period
    panel = (pl.scan_parquet(datasets.dataset_path(ROOT, cfg.strategy.dataset) / datasets.PANEL_FILE)
             .filter(pl.col("date") <= per.end).collect())
    plain = targets(panel, p.model_copy(update={"exits": p.exits.model_copy(update={"book_stop_frac": None})}),
                    per.start, per.end, days_per_year=cfg.market.trading_days_per_year)
    got = targets(panel, p, per.start, per.end, days_per_year=cfg.market.trading_days_per_year)
    stops = sorted(set(got) - set(plain))
    dec = sorted(plain)
    close = panel.select("date", "symbol", "adj_close")
    rows = []
    for s in stops:
        d0 = max(d for d in dec if d < s)
        nxt = min((d for d in dec if d > s), default=per.end)
        w = {k: v for k, v in plain[d0].weights.items() if k != "GOLDBEES"}
        tot = sum(w.values())
        px = close.filter(pl.col("symbol").is_in(list(w)) & pl.col("date").is_in([s, nxt]))
        a = {(d, k): v for d, k, v in px.iter_rows()}
        later = sum(w[k] / tot * a[(nxt, k)] / a[(s, k)] for k in w if (s, k) in a and (nxt, k) in a) - 1
        rows.append((s, nxt, later))
    m = json.loads((ROOT / f"runs/{run}/metrics.json").read_text())["strategy"]
    up = sum(1 for *_, r in rows if r > 0)
    print(f"{name}: CAGR {m['cagr_pct']:.2f}% max DD {m['max_dd_pct']:.2f}% Calmar {m['calmar']:.3f}; stops {len(rows)}, "
          f"picks higher at the next decision {up} (whipsaws), mean move after the stop {sum(r for *_, r in rows) / len(rows):+.2%}")
    for s, nxt, r in rows:
        print(f"  {s} -> {nxt}: picks {r:+.1%}")
