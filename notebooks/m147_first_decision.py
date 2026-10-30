"""M147 (docs/research/m147.md): M106's first paper decision against targets() of the same config on a research dataset.

Reads the paper book's day record (read only), prints picks only in one side, and the weight of each name: the book's
from whole shares x reference close / equity, research's from the target's weights x gross.
Usage: uv run python notebooks/m147_first_decision.py DAY_JSON STRATEGY_CONFIG DATASET_REF YYYY-MM-DD
"""
import json
import sys
from datetime import date
from pathlib import Path

import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.strategy.momentum.targets import targets

ROOT = Path('.')
day, config, ref, d = sys.argv[1], sys.argv[2], sys.argv[3], date.fromisoformat(sys.argv[4])
rec = json.loads(Path(day).read_text())
cfg = load_strategy_config(ROOT / config, ROOT)
print(f"config hash {cfg.hash()} / paper {rec['strategy_config_hash']}")
p = cfg.params
path = datasets.dataset_path(ROOT, ref) / datasets.PANEL_FILE
panel = pl.scan_parquet(path).filter(pl.col('date') <= d).collect()
funds = frozenset(panel.filter(pl.col('security_id').str.starts_with('isin:INF'))['symbol'].unique().to_list())
t = targets(panel, p, date(d.year, d.month, 1), d, fund_symbols=funds, days_per_year=cfg.market.trading_days_per_year)[d]
total = sum(t.weights.values())
res = {s: w / total * t.gross for s, w in t.weights.items()}
eq = rec['decision']['equity_at_close']
book = {o['symbol']: o['shares'] * o['ref_price'] / eq for o in rec['decision']['orders']}
print(f"research {len(res)} names, gross {t.gross:.3f}, weights sum {sum(res.values()):.4f}; paper {len(book)} names, "
      f"weights sum {sum(book.values()):.4f}, paper gross {rec['decision']['gross']}")
print('only research:', sorted(set(res) - set(book)), ' only paper:', sorted(set(book) - set(res)))
print(f"{'symbol':12s} {'research':>9s} {'paper':>9s} {'diff':>8s}")
for s in sorted(set(res) | set(book), key=lambda x: -res.get(x, 0.0)):
    print(f"{s:12s} {res.get(s, 0.0):9.4f} {book.get(s, 0.0):9.4f} {book.get(s, 0.0) - res.get(s, 0.0):8.4f}")
print(f"sum of absolute weight gaps {sum(abs(book.get(s, 0) - res.get(s, 0)) for s in set(res) | set(book)):.4f}")
