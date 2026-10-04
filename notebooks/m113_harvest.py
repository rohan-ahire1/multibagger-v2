"""M113 (docs/research/m113.md): March tax-loss selling on a momentum run, before and after tax.

Usage: uv run python notebooks/m113_harvest.py CONFIG@RUN_ID HARVEST_YAML ...
"""
import sys
from pathlib import Path

import polars as pl

from mb.config.loader import load_harvest_config, load_strategy_config, load_tax_config
from mb.data import datasets
from mb.evaluation.metrics import equity_metrics
from mb.evaluation.tax import after_tax, harvest, realised
from mb.strategy.momentum.run import simulate

ROOT = Path('.')
TAX = load_tax_config(ROOT / 'configs/tax/india_fy2026.yaml')
path, _, rid = sys.argv[1].partition('@')
cfg = load_strategy_config(Path(path), ROOT)
res = simulate(cfg, ROOT)
eq = res.equity.select('date', 'equity')
rec = pl.read_parquet(f'runs/{rid}/equity.parquet').select('date', 'equity')
diff = eq.join(rec, on='date', suffix='_r').select((pl.col('equity') / pl.col('equity_r') - 1).abs().max()).item()
syms = res.fills['symbol'].unique().to_list()
bars = (pl.scan_parquet(datasets.dataset_path(ROOT, cfg.strategy.dataset) / datasets.PANEL_FILE)
        .filter(pl.col('symbol').is_in(syms) & pl.col('date').is_between(eq['date'][0], eq['date'][-1]))
        .select('date', 'symbol', pl.col('adj_open').alias('open'), pl.col('adj_close').alias('close')).collect())
a, b = cfg.strategy.period.start, cfg.strategy.period.end
win = [('whole', a, b)] + [(f.name[:2], f.start, f.end) for f in cfg.baselines.folds]
if b >= cfg.baselines.locked_from:
    win = [('24-26', cfg.baselines.locked_from, b)]
print(f"run {rid} {path} (re-sim diff {diff:.0e})")


def show(name, e, g, extra=''):
    post = after_tax(e, g, TAX)
    pe = post.select('date', pl.col('after').alias('equity'))
    print(f"{name}{extra}  tax paid {post['tax'].sum() / 1e5:,.1f}L")
    for w, x, y in win:
        m, n = equity_metrics(e, x, y), equity_metrics(pe, x, y)
        print(f"  {w:6s} before CAGR {m['cagr_pct']:6.2f}% DD {m['max_dd_pct']:5.2f}% Calmar {m['calmar']:.3f}   "
              f"after CAGR {n['cagr_pct']:6.2f}% DD {n['max_dd_pct']:5.2f}% Calmar {n['calmar']:.3f}")


g0, _ = realised(res.fills, TAX)
show('M106', eq, g0)
for hp in sys.argv[2:]:
    h = load_harvest_config(Path(hp))
    f, scale = harvest(res.fills, bars, eq, cfg.market, TAX, h)
    e = eq.join(scale, on='date').select('date', (pl.col('equity') * pl.col('scale')).alias('equity'))
    g, _ = realised(f, TAX)
    g = g.join(scale, on='date', how='left').with_columns(pl.col('gain') * pl.col('scale').fill_null(1.0)).drop('scale')
    n = f.height - res.fills.height
    show(Path(hp).stem, e, g, f": {n // 2} sell+buy pairs in {f.slice(res.fills.height)['date'].dt.year().n_unique()} "
         f"Marches, cost {1 - scale['scale'][-1]:.3%} of book")
