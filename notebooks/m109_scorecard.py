"""M109 (docs/research/m109.md): the 8-number scorecard (CAGR, DD, Sharpe, Sortino, profit factor, trades, positive years) for final runs.

Sharpe/Sortino: daily returns, annualised x sqrt(252), risk-free 0. Profit factor and trades: closed trades by exit date.
Usage: uv run python notebooks/m109_scorecard.py NAME=RUN_ID ...   (IS 2010-2023, OOS 2024-01-01..2026-09-28)
"""
import sys
from datetime import date

import numpy as np
import polars as pl

WIN = {'IS 2010-23': (date(2010, 1, 4), date(2023, 12, 31)), 'OOS 2024-26': (date(2024, 1, 1), date(2026, 9, 28)),
       'whole': (date(2010, 1, 4), date(2026, 9, 28))}


def card(rid, a, b):
    e = pl.read_parquet(f'runs/{rid}/equity.parquet').sort('date').filter(pl.col('date').is_between(a, b))
    q = e['equity'].to_numpy()
    d = e['date'].to_list()
    r = q[1:] / q[:-1] - 1
    yrs = (d[-1] - d[0]).days / 365.25
    t = pl.read_parquet(f'runs/{rid}/trades.parquet').filter(pl.col('exit_date').is_between(a, b))
    y = e.group_by(pl.col('date').dt.year()).agg(pl.col('equity').first().alias('f'), pl.col('equity').last().alias('l'))
    yr = (y['l'] / y['f'] - 1).to_numpy()
    return dict(cagr=(q[-1] / q[0]) ** (1 / yrs) - 1, dd=(q / np.maximum.accumulate(q) - 1).min(),
                sharpe=r.mean() / r.std() * np.sqrt(252),
                sortino=r.mean() / np.sqrt((np.minimum(r, 0) ** 2).mean()) * np.sqrt(252),
                pf=t.filter(pl.col('pnl') > 0)['pnl'].sum() / -t.filter(pl.col('pnl') < 0)['pnl'].sum(),
                trades=t.height, pos=f"{(yr > 0).sum()}/{len(yr)}")


for arg in sys.argv[1:]:
    name, rid = arg.split('=')
    for w, (a, b) in WIN.items():
        c = card(rid, a, b)
        print(f"{name:14s} {w:12s} CAGR {c['cagr']:6.1%}  DD {c['dd']:6.1%}  Sharpe {c['sharpe']:.2f}  "
              f"Sortino {c['sortino']:.2f}  PF {c['pf']:.2f}  trades {c['trades']:5d}  +years {c['pos']}")
