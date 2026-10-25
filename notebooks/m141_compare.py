"""M141: newest run per strategy version -> Calmar / CAGR / max DD / folds (information table).

Usage: uv run python notebooks/m141_compare.py VERSION ...
"""
import json
import sys
from pathlib import Path


def newest() -> dict[str, str]:
    got: dict[str, str] = {}
    for d in sorted(Path('runs').iterdir()):
        m = d / 'manifest.json'
        if m.exists():
            got[json.loads(m.read_text())['strategy'].split('/')[-1]] = d.name
    return got


runs = newest()
for v in sys.argv[1:]:
    r = runs.get(v)
    if r is None:
        print(v, 'no run')
        continue
    m = json.loads((Path('runs') / r / 'metrics.json').read_text())
    s = m['strategy']
    f = ' / '.join(f"{x['calmar']:.3f}" for x in m.get('folds', {}).values())
    print(f"{v:22s} {r}  {s['calmar']:.3f} ({s['cagr_pct']:.2f}% / {s['max_dd_pct']:.2f}%)  folds {f}")
