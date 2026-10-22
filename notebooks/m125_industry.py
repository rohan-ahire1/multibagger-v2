"""M125 (docs/research/m125.md): industry coverage of M106's buys and how often the industry rule binds (no returns
after the buy). Usage: uv run python notebooks/m125_industry.py
Backtest numbers: notebooks/m120_limits.py report / bootstrap (config-agnostic).
"""
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.sources import nse_industry
from mb.strategy.momentum.targets import ranked, targets, weak_industry_names

ROOT = Path('.')
CFG = 'strategies/momentum/configs'

ref = load_strategy_config(Path(f'{CFG}/m120_ref.yaml'), ROOT)
per, p = ref.strategy.period, ref.params
panel = (pl.scan_parquet(datasets.dataset_path(ROOT, ref.strategy.dataset) / datasets.PANEL_FILE)
         .filter(pl.col('date') <= per.end).collect())
funds = frozenset(panel.filter(pl.col('security_id').str.starts_with('isin:INF'))['symbol'].unique().to_list())
tg = targets(panel, p, per.start, per.end, fund_symbols=funds)
ranks = ranked(panel, p.universe, p.ranking, per.start, per.end, p.portfolio.top_n, 0, None, funds)
for tag in ('sec', 'ind'):
    f = load_strategy_config(Path(f'{CFG}/m125_{tag}.yaml'), ROOT).params.industry_filter
    cls = nse_industry.load(ROOT / f.raw_dir, f.snapshot)
    known = set(cls.filter(pl.col(f.level).is_not_null())['symbol'].to_list())
    weak = weak_industry_names(panel, cls, f, ranks)
    held: set[str] = set()
    rows = []
    for d in sorted(tg):
        names = set(tg[d].weights) - {'GOLDBEES'}
        rows += [(d.year, s in known, s in weak[d]) for s in sorted(names - held)]
        held = names
    df = pl.DataFrame(rows, schema=['year', 'known', 'weak'], orient='row')
    print(f"{tag} ({f.level}, {cls[f.level].n_unique()} classes): {df.height} M106 new buys, classified "
          f"{df['known'].mean():.1%}, in a weak class {df['weak'].sum()} ({df['weak'].mean():.1%})")
    print(df.group_by((pl.col('year') // 4 * 4).alias('from')).agg(pl.len(), pl.col('known').mean(), pl.col('weak').mean())
          .sort('from'))
