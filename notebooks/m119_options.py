"""M119 (docs/research/m119.md): a large-cap options book, F&O stocks ranked by option signals.

info: universe size, signal correlations and pick turnover (signal data only, no returns). curve: re-simulates a config
(options book or M106), checks it against its run record, and caches the before/after-tax curve and the realised gains
(M110 tax model) in reports/m119/curves/. report: stage 1 (each candidate vs ew) and stage 2 (75% M106 + 25% the book,
tax on the two books' gains together), at offsets 0/5/10/15; `report --final` for the locked look.
Usage: uv run python notebooks/m119_options.py info
       uv run python notebooks/m119_options.py curve NAME=CONFIG@RUN_ID   (NAME = cpsN / skewN / ovrN / comboN / ewN /
                                                                          m106N, N = offset; *_final for the locked look)
       uv run python notebooks/m119_options.py report [--final]
"""
import sys
from datetime import date
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config, load_tax_config
from mb.evaluation.metrics import equity_metrics

ROOT = Path('.')
CACHE = ROOT / 'reports/m119/curves'
TAX = ROOT / 'configs/tax/india_fy2026.yaml'
DEV = (date(2010, 1, 4), date(2023, 12, 31))
LOCKED = (date(2024, 1, 1), date(2026, 9, 28))
FOLDS = {'f1': (date(2010, 1, 4), date(2013, 12, 31)), 'f2': (date(2014, 1, 1), date(2017, 12, 31)),
         'f3': (date(2018, 1, 1), date(2023, 12, 31))}
OFFSETS = (0, 5, 10, 15)
KINDS = ('cps', 'skew', 'ovr', 'combo')
BOOK_WEIGHT = 0.25  # the options book's share of the blend at the start


def info():
    from mb.data import datasets
    from mb.strategy.momentum.targets import decision_dates
    from mb.strategy.options_book.run import SIGNALS, signal_table, targets

    cfg = load_strategy_config(ROOT / 'strategies/options_book/configs/m119_ew.yaml', ROOT)
    p, period = cfg.params, cfg.strategy.period
    path = datasets.dataset_path(ROOT, cfg.strategy.dataset)
    panel = (pl.scan_parquet(path / datasets.PANEL_FILE).filter(pl.col('date') <= period.end)
             .select('date', 'symbol', 'series', 'close', 'volume').collect())
    decisions = decision_dates(panel, period.start, period.end, 0)
    t = signal_table(panel, pl.read_parquet(path / 'rename_links.parquet'), p, ROOT, decisions)
    n = t.group_by('date').len()
    print(f"{len(decisions)} month-end decisions, {n.height} with a universe")
    print("universe size, median by year: " + ", ".join(
        f"{y} {int(m)}" for y, m in n.group_by(pl.col('date').dt.year().alias('y')).agg(pl.col('len').median()).sort('y').iter_rows()))
    ranks = t.with_columns(pl.col(c).rank().over('date') for c in SIGNALS)
    for i, a in enumerate(SIGNALS):
        for b in SIGNALS[i + 1:]:
            c = ranks.group_by('date').agg(pl.corr(a, b).alias('r'))['r'].mean()
            print(f"Spearman {a} vs {b}, mean over decisions: {c:.3f}")
    for k, sig in zip(KINDS, ('call_put_spread', 'skew', 'option_volume', 'combo')):
        q = p.model_copy(update={'portfolio': p.portfolio.model_copy(update={'signal': sig, 'top_frac': 0.2})})
        tg = targets(t, q, decisions)
        prev, turns = None, []
        for d in decisions:
            w = {s: 1.0 / len(tg[d].weights) for s in tg[d].weights}
            if prev is not None:
                turns.append(sum(max(0.0, w.get(s, 0.0) - prev.get(s, 0.0)) for s in set(w) | set(prev)))
            prev = w
        print(f"{k}: picks median {int(pl.Series([len(tg[d].weights) for d in decisions]).median())}, "
              f"one-way turnover per month mean {sum(turns) / len(turns):.2f}")


def curve(arg):
    from mb.evaluation.tax import after_tax, realised

    name, spec = arg.split('=')
    path, _, rid = spec.partition('@')
    cfg = load_strategy_config(Path(path), ROOT)
    if cfg.strategy.name == 'options_book':
        from mb.strategy.options_book.run import simulate
        res, _ = simulate(cfg, ROOT)
    else:
        from mb.strategy.momentum.run import simulate
        res = simulate(cfg, ROOT)
    eq = res.equity.select('date', 'equity')
    rec = pl.read_parquet(f'runs/{rid}/equity.parquet').select('date', 'equity')
    diff = eq.join(rec, on='date', suffix='_r').select((pl.col('equity') / pl.col('equity_r') - 1).abs().max()).item()
    tax = load_tax_config(TAX)
    gains, _ = realised(res.fills, tax)
    post = after_tax(eq, gains, tax)
    CACHE.mkdir(parents=True, exist_ok=True)
    eq.join(post.select('date', 'after'), on='date').rename({'equity': 'pre'}).write_parquet(CACHE / f'{name}.parquet')
    gains.write_parquet(CACHE / f'{name}_gains.parquet')
    print(f"{name}: {path} run {rid}, re-sim diff {diff:.0e}")


def blend(a, b):
    """BOOK_WEIGHT of b, the rest a, at the start, not rebalanced; tax on both books' gains together (M110 model)."""
    from mb.evaluation.tax import after_tax

    ca, cb = pl.read_parquet(CACHE / f'{a}.parquet'), pl.read_parquet(CACHE / f'{b}.parquet')
    if ca['date'].to_list() != cb['date'].to_list():
        raise ValueError(f"{a} and {b} are on different calendars")
    ka, kb = (1 - BOOK_WEIGHT) / ca['pre'][0], BOOK_WEIGHT / cb['pre'][0]
    pre = ca.select('date', (pl.col('pre') * ka + cb['pre'] * kb).alias('equity'))
    gains = pl.concat([pl.read_parquet(CACHE / f'{a}_gains.parquet').with_columns(pl.col('gain') * ka),
                       pl.read_parquet(CACHE / f'{b}_gains.parquet').with_columns(pl.col('gain') * kb)]).sort('date', maintain_order=True)
    post = after_tax(pre, gains, load_tax_config(TAX))
    return pre.rename({'equity': 'pre'}).join(post.select('date', 'after'), on='date')


def calmar(c, col, a, b):
    return equity_metrics(c.select('date', pl.col(col).alias('equity')), a, b)['calmar']


def scores(c, window=DEV):
    out = {'pre': calmar(c, 'pre', *window), 'post': calmar(c, 'after', *window)}
    if window == DEV:
        out |= {f: calmar(c, 'pre', *w) for f, w in FOLDS.items()}
    return out


def have(name):
    return (CACHE / f'{name}.parquet').exists()


def report():
    def cell(s):
        return f"{s['pre']:.3f} / {s['post']:.3f}"

    book = {k: {n: scores(pl.read_parquet(CACHE / f'{k}{n}.parquet')) for n in OFFSETS if have(f'{k}{n}')} for k in (*KINDS, 'ew')}
    print("Stage 1, Calmar before / after tax, dev\n")
    print("| offset | ew | " + " | ".join(KINDS) + " |\n|---|---|" + "---|" * len(KINDS))
    for n in OFFSETS:
        print(f"| {n} | " + " | ".join(cell(book[k][n]) if n in book[k] else "-" for k in ('ew', *KINDS)) + " |")
    passed = []
    for k in KINDS:
        if set(book[k]) != set(OFFSETS) or set(book['ew']) != set(OFFSETS):
            continue
        a, b = book['ew'], book[k]
        ok = (all(b[n]['pre'] > a[n]['pre'] for n in OFFSETS) and b[0]['post'] > a[0]['post']
              and sum(b[0][f] > a[0][f] for f in FOLDS) >= 2)
        print(f"{k}: folds before at offset 0 (ew -> {k}) " + ", ".join(f"{a[0][f]:.3f} -> {b[0][f]:.3f}" for f in FOLDS)
              + f"; stage 1 {'pass' if ok else 'fail'}")
        if ok:
            passed.append(k)
    print("\nStage 2, 75% M106 + 25% book, Calmar before / after tax, dev\n")
    names = [k for k in (*KINDS, 'ew') if all(have(f'{k}{n}') for n in OFFSETS)]
    print("| offset | M106 | " + " | ".join(names) + " |\n|---|---|" + "---|" * len(names))
    ref = {n: scores(pl.read_parquet(CACHE / f'm106{n}.parquet')) for n in OFFSETS if have(f'm106{n}')}
    mix = {k: {n: scores(blend(f'm106{n}', f'{k}{n}')) for n in OFFSETS if n in ref} for k in names}
    for n in sorted(ref):
        print(f"| {n} | {cell(ref[n])} | " + " | ".join(cell(mix[k][n]) for k in names) + " |")
    for k in names:
        if set(mix[k]) != set(OFFSETS):
            continue
        a, b = ref, mix[k]
        off0 = b[0]['pre'] > a[0]['pre'] and b[0]['post'] > a[0]['post'] and sum(b[0][f] > a[0][f] for f in FOLDS) >= 2
        rest = all(b[n]['pre'] > a[n]['pre'] for n in (5, 10, 15))
        avg = sum(b[n]['pre'] for n in OFFSETS) / len(OFFSETS)
        tag = '' if k in passed else (' (information only)' if k == 'ew' else ' (failed stage 1)')
        print(f"{k}{tag}: folds before at offset 0 (M106 -> blend) " + ", ".join(f"{a[0][f]:.3f} -> {b[0][f]:.3f}" for f in FOLDS)
              + f"; offset 0 {'pass' if off0 else 'fail'}, offsets 5/10/15 {'pass' if rest else 'fail'}, mean before {avg:.3f}")


def final():
    ref = pl.read_parquet(CACHE / 'm106_final.parquet')
    for k in [f.stem.removesuffix('_final') for f in sorted(CACHE.glob('*_final.parquet')) if not f.stem.startswith('m106')]:
        b = blend('m106_final', f'{k}_final')
        for label, c in (('M106', ref), (f'blend with {k}', b), (f'{k} alone', pl.read_parquet(CACHE / f'{k}_final.parquet'))):
            row = []
            for col in ('pre', 'after'):
                m = equity_metrics(c.select('date', pl.col(col).alias('equity')), *LOCKED)
                row.append(f"{m['cagr_pct']:.2f}% / {m['max_dd_pct']:.2f}% / {m['calmar']:.3f}")
            print(f"{label}: before tax {row[0]}; after tax {row[1]}  (CAGR / max DD / Calmar)")


if __name__ == '__main__':
    if sys.argv[1] == 'info':
        info()
    elif sys.argv[1] == 'curve':
        for a in sys.argv[2:]:
            curve(a)
    elif sys.argv[1:] == ['report', '--final']:
        final()
    else:
        report()
