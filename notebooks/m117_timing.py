"""M117 (docs/research/m117.md): rebalance-day spread, M106 in four tranches, calendar months, "sell in May".

Re-simulates each config (run records keep no fills), checks the pre-tax curve against its run record, and caches the
before/after-tax curves (M110 tax model) in reports/m117/curves/. The report reads only the cache.
Usage: uv run python notebooks/m117_timing.py curve NAME=CONFIG@RUN_ID     (offN = M106 at offset N, hwN = sell in May)
       uv run python notebooks/m117_timing.py report
"""
import sys
from datetime import date
from itertools import combinations
from pathlib import Path
from statistics import mean, pstdev

import polars as pl

from mb.config.loader import load_strategy_config, load_tax_config
from mb.evaluation.metrics import equity_metrics

ROOT = Path('.')
CACHE = ROOT / 'reports/m117/curves'
DEV = (date(2010, 1, 4), date(2023, 12, 31))
FOLDS = {'f1': (date(2010, 1, 4), date(2013, 12, 31)), 'f2': (date(2014, 1, 1), date(2017, 12, 31)),
         'f3': (date(2018, 1, 1), date(2023, 12, 31))}
OFFSETS = range(20)
TRANCHE = (0, 5, 10, 15)
PANEL = ROOT / 'data/datasets/nse_research/2026-10-02b/panel.parquet'


def curve(arg):
    from mb.evaluation.tax import after_tax, realised
    from mb.strategy.momentum.run import simulate

    name, spec = arg.split('=')
    path, _, rid = spec.partition('@')
    cfg = load_strategy_config(Path(path), ROOT)
    res = simulate(cfg, ROOT)
    eq = res.equity.select('date', 'equity')
    rec = pl.read_parquet(f'runs/{rid}/equity.parquet').select('date', 'equity')
    diff = eq.join(rec, on='date', suffix='_r').select((pl.col('equity') / pl.col('equity_r') - 1).abs().max()).item()
    gains, _ = realised(res.fills, load_tax_config(ROOT / 'configs/tax/india_fy2026.yaml'))
    post = after_tax(eq, gains, load_tax_config(ROOT / 'configs/tax/india_fy2026.yaml'))
    CACHE.mkdir(parents=True, exist_ok=True)
    eq.join(post.select('date', 'after'), on='date').rename({'equity': 'pre'}).write_parquet(CACHE / f'{name}.parquet')
    print(f"{name}: {path} run {rid}, re-sim diff {diff:.0e}")


def load(name):
    return pl.read_parquet(CACHE / f'{name}.parquet')


def calmar(c, col, a, b):
    return equity_metrics(c.select('date', pl.col(col).alias('equity')), a, b)['calmar']


def scores(c):
    return {'pre': calmar(c, 'pre', *DEV), 'post': calmar(c, 'after', *DEV), **{f: calmar(c, 'pre', *w) for f, w in FOLDS.items()}}


def monthly(c, col):
    """Calendar-month returns of a daily curve (first month measured from the first close)."""
    m = c.sort('date').group_by_dynamic('date', every='1mo').agg(pl.col(col).last())
    first = c.sort('date')[col][0]
    return m.with_columns(r=pl.col(col) / pl.col(col).shift(1).fill_null(first) - 1).select('date', 'r')


def report():
    s = {n: scores(load(f'off{n}')) for n in OFFSETS}
    print("## Part A: decision offset N (sessions before the month's last), dev 2010-01-04..2023-12-31\n")
    print("| N | Calmar before | after | f1 | f2 | f3 |\n|---|---|---|---|---|---|")
    for n, v in s.items():
        print(f"| {n} | {v['pre']:.3f} | {v['post']:.3f} | {v['f1']:.3f} | {v['f2']:.3f} | {v['f3']:.3f} |")
    for k in ('pre', 'post'):
        xs = [v[k] for v in s.values()]
        near = mean(xs[:3])
        # exact share of 3-day sets out of the 20 whose mean is at least the month-end days' mean
        p = sum(mean(c) >= near - 1e-12 for c in combinations(xs, 3)) / len(list(combinations(xs, 3)))
        print(f"\n{k}: mean {mean(xs):.3f}, sd {pstdev(xs):.3f}, min {min(xs):.3f} (N={xs.index(min(xs))}), "
              f"max {max(xs):.3f} (N={xs.index(max(xs))}); N 0-2 mean {near:.3f} vs N 3-19 mean {mean(xs[3:]):.3f}; "
              f"share of 3-offset sets scoring at least that: {p:.3f}")

    print("\n## Part A: M106 in four tranches (offsets 0/5/10/15, a quarter each)\n")
    cs = [load(f'off{n}') for n in TRANCHE]
    t = cs[0].select('date').with_columns(
        pre=pl.sum_horizontal(0.25 * c['pre'] / c['pre'][0] for c in cs) * 1e6,
        after=pl.sum_horizontal(0.25 * c['after'] / c['pre'][0] for c in cs) * 1e6)
    v = scores(t)
    print(f"tranche: Calmar before {v['pre']:.3f}, after {v['post']:.3f}, folds before f1/f2/f3 "
          f"{v['f1']:.3f}/{v['f2']:.3f}/{v['f3']:.3f}; mean of the four sleeves before "
          f"{mean(s[n]['pre'] for n in TRANCHE):.3f}, after {mean(s[n]['post'] for n in TRANCHE):.3f}")
    for k in ('pre', 'after'):
        m = equity_metrics(t.select('date', pl.col(k).alias('equity')), *DEV)
        print(f"  {k}: CAGR {m['cagr_pct']:.2f}% DD {m['max_dd_pct']:.2f}%")

    print("\n## Part B: calendar months (information only), 2010-2023\n")
    book = pl.concat([monthly(load(f'off{n}'), 'pre') for n in TRANCHE]).group_by('date').agg(pl.col('r').mean())
    bars = (pl.scan_parquet(PANEL).filter(pl.col('symbol').is_in(['JUNIORBEES', 'NIFTYBEES'])
                                          & pl.col('date').is_between(*DEV)).select('symbol', 'date', 'adj_close').collect())
    cols = {'M106 (4 offsets)': book}
    for sym in ('JUNIORBEES', 'NIFTYBEES'):
        cols[sym] = monthly(bars.filter(pl.col('symbol') == sym), 'adj_close')
    print("| month | " + " | ".join(f"{k} mean / up years" for k in cols) + " |\n|---|" + "---|" * len(cols))
    for mo in range(1, 13):
        cells = []
        for r in cols.values():
            x = r.filter(pl.col('date').dt.month() == mo)['r']
            cells.append(f"{100 * x.mean():+.2f}% / {(x > 0).sum()} of {len(x)}")
        print(f"| {date(2000, mo, 1):%b} | " + " | ".join(cells) + " |")
    for k, r in cols.items():
        half = r.with_columns(may_oct=pl.col('date').dt.month().is_between(5, 10)).group_by('may_oct').agg(pl.col('r').mean())
        g = dict(half.iter_rows())
        print(f"{k}: mean month May-Oct {100 * g[True]:+.2f}%, Nov-Apr {100 * g[False]:+.2f}%")

    hw = [n for n in TRANCHE if (CACHE / f'hw{n}.parquet').exists()]
    if not hw:
        return
    print("\n## Part C: sell in May (decisions dated Apr-Sep risk-off)\n")
    print("| offset | M106 before / after | sell in May before / after | f1 / f2 / f3 before (M106 -> candidate) |\n|---|---|---|---|")
    h = {n: scores(load(f'hw{n}')) for n in hw}
    for n in hw:
        a, b = s[n], h[n]
        print(f"| {n} | {a['pre']:.3f} / {a['post']:.3f} | {b['pre']:.3f} / {b['post']:.3f} | "
              + " / ".join(f"{a[f]:.3f} -> {b[f]:.3f}" for f in FOLDS) + " |")
    if set(hw) == set(TRANCHE):
        a, b = s[0], h[0]
        off0 = b['pre'] > a['pre'] and b['post'] > a['post'] and sum(b[f] > a[f] for f in FOLDS) >= 2
        rest = all(h[n]['pre'] > s[n]['pre'] for n in (5, 10, 15))
        print(f"\noffset 0 bar: {'pass' if off0 else 'fail'}; offsets 5/10/15 bar: {'pass' if rest else 'fail'}")


if __name__ == '__main__':
    if sys.argv[1] == 'curve':
        for a in sys.argv[2:]:
            curve(a)
    else:
        report()
