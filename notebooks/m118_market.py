"""M118 (docs/research/m118.md): F&O market signals as a second risk-off switch on M106.

info: how many month-end dev decisions each signal turns risk-off while JUNIORBEES alone is risk-on (signal data
only, no returns). curve: re-simulates a config, checks it against its run record and caches before/after-tax curves
(M110 tax model) in reports/m118/curves/. report: the pass bar against M106's cached curves from M117.
Usage: uv run python notebooks/m118_market.py info
       uv run python notebooks/m118_market.py curve NAME=CONFIG@RUN_ID     (NAME = vrpN / pcrN / fiiN, N = offset)
       uv run python notebooks/m118_market.py report
"""
import sys
from datetime import date
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config, load_tax_config
from mb.evaluation.metrics import equity_metrics

ROOT = Path('.')
CACHE = ROOT / 'reports/m118/curves'
M106 = ROOT / 'reports/m117/curves'  # M106 at offsets 0/5/10/15 (M117), same dataset and tax model
DEV = (date(2010, 1, 4), date(2023, 12, 31))
FOLDS = {'f1': (date(2010, 1, 4), date(2013, 12, 31)), 'f2': (date(2014, 1, 1), date(2017, 12, 31)),
         'f3': (date(2018, 1, 1), date(2023, 12, 31))}
OFFSETS = (0, 5, 10, 15)
KINDS = ('vrp', 'pcr', 'fii')
PANEL = ROOT / 'data/datasets/nse_research/2026-10-02b/panel.parquet'


def info():
    from mb.data import market
    from mb.strategy.momentum.run import market_values
    from mb.strategy.momentum.targets import risk_on

    panel = pl.scan_parquet(PANEL).filter(pl.col('symbol').is_in(['JUNIORBEES', 'NIFTYBEES'])).select(
        'date', 'symbol', 'adj_close').collect()
    days = panel.filter((pl.col('symbol') == 'JUNIORBEES') & pl.col('date').is_between(*DEV)).select('date')
    ends = days.group_by(pl.col('date').dt.strftime('%Y-%m').alias('ym')).agg(pl.col('date').max())['date'].sort().to_list()
    trend = risk_on(panel, 'JUNIORBEES', 200, ends)
    print(f"{len(ends)} month-end decisions, JUNIORBEES risk-off at {sum(not v for v in trend.values())}\n")
    flags = {}
    for k in KINDS:
        p = load_strategy_config(ROOT / f'strategies/momentum/configs/m118_{k}.yaml', ROOT).params
        ms = p.regime.market_signal
        s = market_values(p, ROOT)
        flags[k] = (market.vrp_on(s, panel, ms.rv_symbol, ms.rv_sessions, ends) if ms.kind == 'vrp'
                    else market.ranked_on(s, ends, ms.window_sessions, ms.min_pct))
    years = sorted({d.year for d in ends})
    print("| signal | off in all | off while trend on | " + " | ".join(str(y) for y in years) + " |")
    print("|---|---|---|" + "---|" * len(years))
    for k, f in flags.items():
        add = [d for d in ends if trend[d] and not f[d]]
        print(f"| {k} | {sum(not v for v in f.values())} | {len(add)} | "
              + " | ".join(str(sum(d.year == y for d in add)) for y in years) + " |")
    for a in KINDS:
        for b in KINDS:
            if a < b:
                both = sum(not flags[a][d] and not flags[b][d] for d in ends)
                print(f"{a} and {b} both off: {both}")


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
    tax = load_tax_config(ROOT / 'configs/tax/india_fy2026.yaml')
    gains, _ = realised(res.fills, tax)
    post = after_tax(eq, gains, tax)
    CACHE.mkdir(parents=True, exist_ok=True)
    eq.join(post.select('date', 'after'), on='date').rename({'equity': 'pre'}).write_parquet(CACHE / f'{name}.parquet')
    print(f"{name}: {path} run {rid}, re-sim diff {diff:.0e}")


def calmar(c, col, a, b):
    return equity_metrics(c.select('date', pl.col(col).alias('equity')), a, b)['calmar']


def scores(c):
    return {'pre': calmar(c, 'pre', *DEV), 'post': calmar(c, 'after', *DEV), **{f: calmar(c, 'pre', *w) for f, w in FOLDS.items()}}


def report():
    ref = {n: scores(pl.read_parquet(M106 / f'off{n}.parquet')) for n in OFFSETS}
    print("| offset | M106 before / after | " + " | ".join(f"{k} before / after" for k in KINDS) + " |")
    print("|---|---|" + "---|" * len(KINDS))
    got = {k: {n: scores(pl.read_parquet(CACHE / f'{k}{n}.parquet')) for n in OFFSETS
               if (CACHE / f'{k}{n}.parquet').exists()} for k in KINDS}
    for n in OFFSETS:
        cells = [f"{got[k][n]['pre']:.3f} / {got[k][n]['post']:.3f}" if n in got[k] else "-" for k in KINDS]
        print(f"| {n} | {ref[n]['pre']:.3f} / {ref[n]['post']:.3f} | " + " | ".join(cells) + " |")
    print()
    for k in KINDS:
        if 0 not in got[k]:
            continue
        a, b = ref[0], got[k][0]
        print(f"{k} folds before (M106 -> candidate): " + ", ".join(f"{a[f]:.3f} -> {b[f]:.3f}" for f in FOLDS))
        if set(got[k]) != set(OFFSETS):
            continue
        off0 = b['pre'] > a['pre'] and b['post'] > a['post'] and sum(b[f] > a[f] for f in FOLDS) >= 2
        rest = all(got[k][n]['pre'] > ref[n]['pre'] for n in (5, 10, 15))
        avg = sum(got[k][n]['pre'] for n in OFFSETS) / len(OFFSETS)
        print(f"  offset 0 bar: {'pass' if off0 else 'fail'}; offsets 5/10/15 bar: {'pass' if rest else 'fail'}; "
              f"mean before-tax Calmar over offsets {avg:.3f} (M106 {sum(ref[n]['pre'] for n in OFFSETS) / 4:.3f})")


if __name__ == '__main__':
    if sys.argv[1] == 'info':
        info()
    elif sys.argv[1] == 'curve':
        for a in sys.argv[2:]:
            curve(a)
    else:
        report()
