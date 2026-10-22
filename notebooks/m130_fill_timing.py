"""M130 (docs/research/m130.md): M106 with other fill prices (information).

Usage:
  uv run python notebooks/m130_fill_timing.py CONFIG ...   # each config at modes open / close / typical / delay1
"""
import sys
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.evaluation.metrics import equity_metrics
from mb.strategy.momentum import run as mrun

ROOT = Path('.')
ORIG = mrun.simulate_targets
MODES = ['open', 'close', 'typical', 'delay1']


def fill_bars(bars: pl.DataFrame, extra: pl.DataFrame, mode: str) -> pl.DataFrame:
    """`bars` (date, symbol, open, close) with `open`, the fill price, replaced as `mode` says."""
    if mode == 'open':
        return bars
    if mode == 'close':  # the decision's trades fill at the next session's close
        return bars.with_columns(pl.col('close').alias('open'))
    if mode == 'typical':  # (O + H + L + C) / 4 of the next session, a VWAP stand-in
        b = bars.join(extra, on=['date', 'symbol'], how='left')
        return b.select('date', 'symbol', ((pl.col('open') + pl.col('h') + pl.col('l') + pl.col('close')) / 4)
                        .fill_null(pl.col('open')).alias('open'), 'close')
    raise ValueError(mode)


def main(paths: list[str]) -> None:
    for path in paths:
        cfg = load_strategy_config(Path(path), ROOT)
        extra = (pl.scan_parquet(datasets.dataset_path(ROOT, cfg.strategy.dataset) / datasets.PANEL_FILE)
                 .filter(pl.col('date') <= cfg.strategy.period.end)
                 .select('date', 'symbol', pl.col('adj_high').alias('h'), pl.col('adj_low').alias('l')).collect())
        a, b = cfg.strategy.period.start, cfg.strategy.period.end
        for mode in MODES:
            def patched(tg, bars, days, *args, _m=mode, **kw):
                if _m == 'delay1':  # the open of the session after next; a target on the last two sessions is dropped
                    nxt = {d: n for d, n in zip(days, days[1:])}
                    tg = {nxt[d]: t for d, t in tg.items() if d in nxt and nxt[d] != days[-1]}
                    return ORIG(tg, bars, days, *args, **kw)
                return ORIG(tg, fill_bars(bars, extra, _m), days, *args, **kw)
            mrun.simulate_targets = patched
            try:
                eq = mrun.simulate(cfg, ROOT).equity.select('date', 'equity')
            finally:
                mrun.simulate_targets = ORIG
            cells = []
            for w, x, y in [('whole', a, b)] + [(f.name[:2], f.start, f.end) for f in cfg.baselines.folds]:
                m = equity_metrics(eq, x, y)
                cells.append(f"{w} {m['calmar']:.3f} ({m['cagr_pct']:.2f}% / {m['max_dd_pct']:.2f}%)")
            print(f"{Path(path).stem:18s} {mode:8s} " + '  '.join(cells), flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
