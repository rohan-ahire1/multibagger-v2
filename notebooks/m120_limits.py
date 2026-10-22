"""M120 (docs/research/m120.md): up-limit hits as a buy filter on M106.

Usage:
  uv run python notebooks/m120_limits.py info                      # hit counts of M106's new buys (no returns)
  uv run python notebooks/m120_limits.py report CONFIG@RUN ...     # before/after tax, whole period and folds
"""
import sys
from collections import Counter
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config, load_tax_config
from mb.data import datasets
from mb.evaluation.metrics import equity_metrics
from mb.evaluation.tax import after_tax, realised
from mb.strategy.momentum.run import simulate
from mb.strategy.momentum.targets import limit_hits, targets

ROOT = Path('.')
TAX = load_tax_config(ROOT / 'configs/tax/india_fy2026.yaml')
CFG = 'strategies/momentum/configs'


def info() -> None:
    ref = load_strategy_config(Path(f'{CFG}/m120_ref.yaml'), ROOT)
    lh = load_strategy_config(Path(f'{CFG}/m120_lh20.yaml'), ROOT).params.limit_hits
    per = ref.strategy.period
    src = datasets.dataset_path(ROOT, ref.strategy.dataset) / datasets.PANEL_FILE
    panel = pl.scan_parquet(src).filter(pl.col('date') <= per.end).collect()
    funds = frozenset(panel.filter(pl.col('security_id').str.starts_with('isin:INF'))['symbol'].unique().to_list())
    tg = targets(panel, ref.params, per.start, per.end, fund_symbols=funds)
    dates = sorted(tg)
    hits = limit_hits(panel, lh, dates)
    held: set[str] = set()
    rows = []
    for d in dates:
        names = {s for s in tg[d].weights if s not in ('GOLDBEES',)}
        for s in sorted(names - held):
            rows.append((d.year, s, hits[d].get(s, 0)))
        held = names
    df = pl.DataFrame(rows, schema=['year', 'symbol', 'hits'], orient='row')
    print(f"M106 new buys 2010-23: {df.height}; hits in last 252 sessions: median {df['hits'].median()}, "
          f"p75 {df['hits'].quantile(0.75)}, p90 {df['hits'].quantile(0.9)}, max {df['hits'].max()}")
    for k in (5, 10, 20, 30):
        print(f"  more than {k}: {df.filter(pl.col('hits') > k).height} ({df.filter(pl.col('hits') > k).height / df.height:.1%})")
    print(df.group_by('year').agg(pl.len().alias('buys'), (pl.col('hits') > 10).sum().alias('gt10'),
                                  (pl.col('hits') > 20).sum().alias('gt20'), pl.col('hits').median().alias('median'))
          .sort('year'))
    allc = Counter(n for c in hits.values() for n in c.values())
    print(f"all symbol-decisions with hits > 20: {sum(v for k, v in allc.items() if k > 20) / sum(allc.values()):.1%}")


def report(pairs: list[str]) -> None:
    for pr in pairs:
        path, _, rid = pr.partition('@')
        cfg = load_strategy_config(Path(path), ROOT)
        res = simulate(cfg, ROOT)
        eq = res.equity.select('date', 'equity')
        rec = pl.read_parquet(f'runs/{rid}/equity.parquet').select('date', 'equity')
        diff = eq.join(rec, on='date', suffix='_r').select((pl.col('equity') / pl.col('equity_r') - 1).abs().max()).item()
        g, _ = realised(res.fills, TAX)
        post = after_tax(eq, g, TAX).select('date', pl.col('after').alias('equity'))
        a, b = cfg.strategy.period.start, cfg.strategy.period.end
        print(f"{Path(path).stem} run {rid} (re-sim diff {diff:.0e})")
        for w, x, y in [('whole', a, b)] + [(f.name[:2], f.start, f.end) for f in cfg.baselines.folds]:
            m, n = equity_metrics(eq, x, y), equity_metrics(post, x, y)
            print(f"  {w:6s} before CAGR {m['cagr_pct']:6.2f}% DD {m['max_dd_pct']:5.2f}% Calmar {m['calmar']:.3f}   "
                  f"after CAGR {n['cagr_pct']:6.2f}% DD {n['max_dd_pct']:5.2f}% Calmar {n['calmar']:.3f}")


if __name__ == '__main__':
    info() if sys.argv[1] == 'info' else report(sys.argv[2:])
