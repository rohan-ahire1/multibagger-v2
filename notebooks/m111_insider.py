"""M111 (docs/research/m111.md): before/after-tax Calmar of insider-filter runs vs M106 on the windows where the rule is live.

Usage: uv run python notebooks/m111_insider.py NAME=CONFIG@RUN_ID ...   (first one is the reference)
"""
import sys
from datetime import date
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config, load_tax_config
from mb.evaluation.metrics import equity_metrics
from mb.evaluation.tax import after_tax, realised
from mb.strategy.momentum.run import simulate

ROOT = Path('.')
TAX = load_tax_config(ROOT / 'configs/tax/india_fy2026.yaml')
WIN = {'pre-rule 2010-16': (date(2010, 1, 4), date(2016, 3, 31)), 'live 2016-04..23': (date(2016, 4, 1), date(2023, 12, 31)),
       'f2 2014-17': (date(2014, 1, 1), date(2017, 12, 31)), 'f3 2018-23': (date(2018, 1, 1), date(2023, 12, 31)),
       'locked 24-26/04': (date(2024, 1, 1), date(2026, 4, 30))}

ref = None
for arg in sys.argv[1:]:
    name, spec = arg.split('=')
    path, _, rid = spec.partition('@')
    cfg = load_strategy_config(Path(path), ROOT)
    res = simulate(cfg, ROOT)
    eq = res.equity.select('date', 'equity')
    rec = pl.read_parquet(f'runs/{rid}/equity.parquet').select('date', 'equity')
    diff = eq.join(rec, on='date', suffix='_r').select((pl.col('equity') / pl.col('equity_r') - 1).abs().max()).item()
    g, _ = realised(res.fills, TAX)
    post = after_tax(eq, g, TAX).select('date', pl.col('after').alias('equity'))
    buys = set(res.holdings.select('symbol', 'entry_date').iter_rows())
    if ref is None:
        ref = buys
    print(f"{name}: run {rid} (re-sim diff {diff:.0e}); entries {len(buys)}, not in ref {len(buys - ref)}")
    for w, (a, b) in WIN.items():
        if b > cfg.strategy.period.end or a < cfg.strategy.period.start:
            continue
        m, n = equity_metrics(eq, a, b), equity_metrics(post, a, b)
        print(f"  {w:18s} before CAGR {m['cagr_pct']:6.2f}% DD {m['max_dd_pct']:5.2f}% Calmar {m['calmar']:.3f}   "
              f"after CAGR {n['cagr_pct']:6.2f}% DD {n['max_dd_pct']:5.2f}% Calmar {n['calmar']:.3f}")
