"""M141 information stage (no returns): of the reference books' stock buys, the share with a usable latest quarter and
the share each fundamentals rule would flag, by fold.

Usage: uv run python notebooks/m141_info.py RUN_ID ...   (reference runs, e.g. m136_ref and m141_ref_offN)
"""
import sys
from pathlib import Path

import polars as pl

from mb.data import fundamentals
from mb.sources import nse_results

PANEL = 'data/datasets/nse_research/2026-10-23/panel.parquet'
SKIP = {'GOLDBEES'}
MAX_AGE = 200
FOLDS = [('f1', 2010, 2013), ('f2', 2014, 2017), ('f3', 2018, 2023)]

filings = nse_results.load(Path('data/raw/nse_results'))
days = sorted(pl.scan_parquet(PANEL).select('date').unique().collect()['date'].to_list())
prev = {d: days[i - 1] for i, d in enumerate(days) if i}
for run in sys.argv[1:]:
    t = pl.read_parquet(Path('runs') / run / 'trades.parquet').filter(~pl.col('symbol').is_in(list(SKIP)))
    buys = [(s, prev[e]) for s, e in t.select('symbol', 'entry_date').unique().iter_rows()]
    dec = sorted({d for _, d in buys})
    cov = fundamentals.coverage(filings, dec, MAX_AGE)
    fl = {r: fundamentals.flags(filings, r, dec, MAX_AGE) for r in ('loss', 'yoy_decline')}
    print(run, f'{len(buys)} buys')
    for name, y0, y1 in [('all', 2010, 2023)] + FOLDS:
        b = [(s, d) for s, d in buys if y0 <= d.year <= y1]
        n = len(b) or 1
        c = sum(s in cov[d] for s, d in b) / n
        out = ' '.join(f"{r} {sum(s in fl[r][d] for s, d in b) / n:.1%}" for r in fl)
        print(f'  {name:4s} n={len(b):4d} covered {c:.1%}  flagged: {out}')
