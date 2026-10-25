"""M143 information stage (no returns): coverage of the turnover ratio among M106's ranked names and buys, and the
share of M106's new buys that the top-20% / top-40% rules would block, by fold.

Usage: uv run python notebooks/m143_info.py
"""
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import fundamentals, datasets
from mb.sources import nse_results
from mb.strategy.momentum.targets import ranked, targets, top_frac

ROOT = Path('.')
cfg = load_strategy_config(ROOT / 'strategies/momentum/configs/m136_ref.yaml', ROOT)
p, per = cfg.params, cfg.strategy.period
panel = (pl.scan_parquet(datasets.dataset_path(ROOT, cfg.strategy.dataset) / datasets.PANEL_FILE)
         .filter(pl.col('date') <= per.end).collect())
funds = frozenset(panel.filter(pl.col('security_id').str.starts_with('isin:INF'))['symbol'].unique().to_list())
ranks = ranked(panel, p.universe, p.ranking, per.start, per.end, p.portfolio.top_n, 0, None, funds)
tg = targets(panel, p, per.start, per.end, fund_symbols=funds)
tr = fundamentals.turnover_ratio(nse_results.load(ROOT / 'data/raw/nse_results'), panel, list(ranks), 50, 200)
held: set[str] = set()
rows = []
for d in sorted(tg):
    pick = {s for s in tg[d].weights if s not in ('GOLDBEES',)}
    new = pick - held
    cov = {s: v for s, v in tr[d].items() if s in set(ranks[d])}
    f20, f40 = top_frac(cov, 0.2), top_frac(cov, 0.4)
    for s in new:
        rows.append((d.year, s in cov, s in f20, s in f40))
    rows_rank = len(cov) / max(len(ranks[d]), 1)
    held = pick
    if d.month == 12:
        print(f'{d}: ranked {len(ranks[d])}, with ratio {rows_rank:.0%}, median ratio {pl.Series(list(cov.values())).median():.4f}')
x = pl.DataFrame(rows, schema=['year', 'covered', 'top20', 'top40'], orient='row')
for name, a, b in [('all', 2010, 2023), ('f1', 2010, 2013), ('f2', 2014, 2017), ('f3', 2018, 2023)]:
    g = x.filter(pl.col('year').is_between(a, b))
    print(f"{name}: new buys {g.height}, covered {g['covered'].mean():.1%}, in top 20% {g['top20'].mean():.1%}, "
          f"in top 40% {g['top40'].mean():.1%}")
