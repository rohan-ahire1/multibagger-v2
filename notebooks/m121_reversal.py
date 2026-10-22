"""M121 (docs/research/m121.md): how often M106's new buys are long-term (month 13-36) winners. No returns after the buy.

Usage: uv run python notebooks/m121_reversal.py
Backtest numbers: notebooks/m120_limits.py report / bootstrap (config-agnostic).
"""
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.strategy.momentum.targets import long_winners, ranked, targets

ROOT = Path('.')
CFG = 'strategies/momentum/configs'

ref = load_strategy_config(Path(f'{CFG}/m120_ref.yaml'), ROOT)
per, p = ref.strategy.period, ref.params
panel = (pl.scan_parquet(datasets.dataset_path(ROOT, ref.strategy.dataset) / datasets.PANEL_FILE)
         .filter(pl.col('date') <= per.end).collect())
funds = frozenset(panel.filter(pl.col('security_id').str.starts_with('isin:INF'))['symbol'].unique().to_list())
tg = targets(panel, p, per.start, per.end, fund_symbols=funds)
ranks = ranked(panel, p.universe, p.ranking, per.start, per.end, p.portfolio.top_n, 0, None, funds)
for tag in ('lr10', 'lr20'):
    lr = load_strategy_config(Path(f'{CFG}/m121_{tag}.yaml'), ROOT).params.long_reversal
    top = long_winners(panel, lr, ranks)
    held: set[str] = set()
    rows = []
    for d in sorted(tg):
        names = set(tg[d].weights) - {'GOLDBEES'}
        rows += [(d.year, s in top[d]) for s in sorted(names - held)]
        held = names
    df = pl.DataFrame(rows, schema=['year', 'top'], orient='row')
    print(f"{tag}: {df['top'].sum()} of {df.height} M106 new buys ({df['top'].mean():.1%}) are in the top "
          f"{lr.drop_frac:.0%} of month 13-36 returns")
    print(df.group_by('year').agg(pl.len().alias('buys'), pl.col('top').sum().alias('top')).sort('year')
          .transpose(include_header=False))
