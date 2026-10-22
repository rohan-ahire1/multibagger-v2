"""Four-offset pre-screen table (loop journal, cycle 7 lesson): candidate vs reference at offsets 0/5/10/15.

Usage:
  uv run python notebooks/prescreen.py REF_VERSION CANDIDATE_VERSION ...
e.g. `notebooks/prescreen.py m120_ref m133_p25`: the newest run of `<version>`, `<version>_off5`, `_off10`, `_off15`
(and `_slip25` if run) under runs/, by the `strategy` field of manifest.json. Prints Calmar (CAGR / DD), the folds at
offset 0, and whether each candidate wins every offset and fold.
"""
import json
import sys
from pathlib import Path

SUFFIXES = ['', '_off5', '_off10', '_off15', '_slip25']


def newest() -> dict[str, str]:
    got: dict[str, str] = {}
    for d in sorted(Path('runs').iterdir()):
        m = d / 'manifest.json'
        if m.exists():
            got[json.loads(m.read_text())['strategy'].split('/')[-1]] = d.name  # sorted by id: last is newest
    return got


def metrics(run: str) -> dict:
    return json.loads((Path('runs') / run / 'metrics.json').read_text())


def main(ref: str, cands: list[str]) -> None:
    runs = newest()
    rows = {}
    for v in [ref] + cands:
        rows[v] = {s: runs.get(v + s) for s in SUFFIXES}
    print('| | ' + ' | '.join([ref] + cands) + ' |')
    print('|---' * (len(cands) + 2) + '|')
    wins = {c: True for c in cands}
    for s in SUFFIXES:
        if rows[ref][s] is None:
            continue
        cells, base = [], metrics(rows[ref][s])['strategy']['calmar']
        for v in [ref] + cands:
            r = rows[v][s]
            if r is None:
                cells.append('—')
                continue
            m = metrics(r)['strategy']
            cells.append(f"{m['calmar']:.3f} ({m['cagr_pct']:.2f}% / {m['max_dd_pct']:.2f}%)")
            if v != ref and m['calmar'] <= base:
                wins[v] = False
        print(f"| {s or 'offset 0'} | " + ' | '.join(cells) + ' |')
    cells = []
    f0 = [x['calmar'] for x in metrics(rows[ref]['']).get('folds', {}).values()]
    for v in [ref] + cands:
        f = [x['calmar'] for x in metrics(rows[v]['']).get('folds', {}).values()]
        if v != ref and any(a <= b for a, b in zip(f, f0)):
            wins[v] = False
        cells.append(' / '.join(f'{x:.3f}' for x in f))
    print('| folds (offset 0) | ' + ' | '.join(cells) + ' |')
    for c in cands:
        print(f"{c}: {'wins every offset run and fold' if wins[c] else 'fails the pre-screen'}"
              f" (runs: {', '.join(r for r in rows[c].values() if r)})")


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
