"""M110 (docs/research/m110.md): before-tax and after-tax CAGR, max DD and Calmar of momentum configs.

Re-simulates each config (run records keep no fills), checks the pre-tax curve against the run record when a run id is
given, then applies configs/tax/india_fy2026.yaml (src/mb/evaluation/tax.py). Folds slice the whole-period after-tax
curve (tax paid at each FY end); 'whole+liq' also taxes the open lots at the last session.
Usage: uv run python notebooks/m110_tax.py NAME=CONFIG[@RUN_ID] ...
"""
import sys
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config, load_tax_config
from mb.evaluation.metrics import equity_metrics
from mb.evaluation.tax import BUCKETS, after_tax, realised, unrealised
from mb.strategy.momentum.run import simulate

ROOT = Path('.')
TAX = load_tax_config(ROOT / 'configs/tax/india_fy2026.yaml')


def row(label, e, a, b):
    m = equity_metrics(e, a, b)
    return f"{label:16s} CAGR {m['cagr_pct']:6.2f}%  DD {m['max_dd_pct']:6.2f}%  Calmar {m['calmar']:.2f}"


for arg in sys.argv[1:]:
    name, spec = arg.split('=')
    path, _, rid = spec.partition('@')
    cfg = load_strategy_config(Path(path), ROOT)
    res = simulate(cfg, ROOT)
    eq = res.equity.select('date', 'equity')
    if rid:
        rec = pl.read_parquet(f'runs/{rid}/equity.parquet').select('date', 'equity')
        diff = eq.join(rec, on='date', suffix='_rec').select((pl.col('equity') / pl.col('equity_rec') - 1).abs().max()).item()
        print(f"{name}: max |pre-tax / run {rid} - 1| = {diff:.2e}")
    last = eq['date'][-1]
    gains, lots = realised(res.fills, TAX)
    close = (pl.scan_parquet(next((ROOT / 'data/datasets').glob(cfg.strategy.dataset.replace('@', '/'))) / 'panel.parquet')
             .filter(pl.col('date') <= last).sort('date').group_by('symbol').agg(pl.col('adj_close').last()).collect())
    open_g = unrealised(lots, dict(close.iter_rows()), last, TAX)
    paid = after_tax(eq, gains, TAX)
    liq = after_tax(eq, gains, TAX, liquidate=open_g)
    by = gains.group_by('bucket').agg(pl.col('gain').sum())
    tot = by['gain'].sum()
    print(f"{name}: realised gains by bucket (share of net) "
          + "  ".join(f"{b} {by.filter(pl.col('bucket') == b)['gain'].sum() / tot:5.1%}" for b in BUCKETS)
          + f"  | tax paid {paid['tax'].sum() / 1e5:,.1f}L, open gains at end {sum(open_g.values()) / 1e5:,.1f}L")
    a, b = cfg.strategy.period.start, cfg.strategy.period.end
    print(row('  pre  whole', eq, a, b))
    print(row('  post whole', paid.select('date', pl.col('after').alias('equity')), a, b))
    print(row('  post whole+liq', liq.select('date', pl.col('after').alias('equity')), a, b))
    for f in cfg.baselines.folds:
        print(row(f'  pre  {f.name[:2]}', eq, f.start, f.end) + '   |' +
              row(f'post {f.name[:2]}', paid.select('date', pl.col('after').alias('equity')), f.start, f.end)[8:])
