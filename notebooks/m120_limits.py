"""M120 (docs/research/m120.md): up-limit hits as a buy filter on M106.

Usage:
  uv run python notebooks/m120_limits.py info                      # hit counts of M106's new buys (no returns)
  uv run python notebooks/m120_limits.py report CONFIG@RUN ...     # before/after tax, whole period and folds
  uv run python notebooks/m120_limits.py bootstrap REF_RUN RUN ...  # M20 stationary bootstrap: RUN's Calmar above REF_RUN's
"""
import sys
from collections import Counter
from pathlib import Path

import numpy as np
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


def bootstrap(ref: str, runs: list[str], block: int = 63, n: int = 5000, seed: int = 20260930, chunk: int = 250) -> None:
    """M20 settings (as notebooks/m96_bootstrap.py): resample the daily returns of all curves together."""
    curves = [pl.read_parquet(f'runs/{r}/equity.parquet').select('date', 'equity') for r in [ref] + runs]
    days = curves[0].select('date')
    eq = np.column_stack([days.join(c, on='date', how='left')['equity'].to_numpy() for c in curves])
    assert not np.isnan(eq).any()
    rets = eq[1:] / eq[:-1] - 1
    years = (days['date'][-1] - days['date'][0]).days / 365.25
    T = rets.shape[0]

    def calmar(r: np.ndarray) -> np.ndarray:
        path = np.concatenate([np.ones_like(r[..., :1, :]), np.cumprod(1 + r, axis=-2)], axis=-2)
        cagr = path[..., -1, :] ** (1 / years) - 1
        return cagr / (1 - path / np.maximum.accumulate(path, axis=-2)).max(axis=-2)

    rng = np.random.default_rng(seed)
    cal = []
    for _ in range(n // chunk):
        start = rng.integers(0, T, size=(chunk, T))
        new = rng.random((chunk, T)) < 1 / block
        new[:, 0] = True
        idx = np.empty((chunk, T), dtype=np.int64)
        idx[:, 0] = start[:, 0]
        for t in range(1, T):
            idx[:, t] = np.where(new[:, t], start[:, t], (idx[:, t - 1] + 1) % T)
        cal.append(calmar(rets[idx]))
    c = np.concatenate(cal)
    c0 = calmar(rets)
    for j, r in enumerate(runs, start=1):
        d = c[:, j] - c[:, 0]
        print(f"{r} vs {ref}: actual Calmar {c0[j]:.3f} vs {c0[0]:.3f}; higher in {np.mean(d > 0):.1%} of {len(d)}; "
              f"diff 5-95% [{np.quantile(d, .05):+.3f}, {np.quantile(d, .95):+.3f}]")


if __name__ == '__main__':
    {'info': lambda: info(), 'report': lambda: report(sys.argv[2:]),
     'bootstrap': lambda: bootstrap(sys.argv[2], sys.argv[3:])}[sys.argv[1]]()
