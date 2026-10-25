"""M146 (docs/research/m146.md): candidate factors for unexplained jumps that sit on a feed action with no factor.

For each (symbol, jump date): cum close (last session before the jump), ex open and close, the observed ratio, and the
face value from NSE results filings near the date (for rights at face value + premium). No returns are used.
Usage: uv run python notebooks/m146_ca_audit.py
"""
from pathlib import Path

import polars as pl

from mb.sources import nse_results

DS = Path('data/datasets/nse_research/2026-10-25')
u = pl.read_parquet(DS / 'unexplained_jumps.parquet')
ca = pl.read_parquet('data/raw/nse_corporate_actions/nse_corporate_actions.parquet')
ov = pl.read_csv('configs/data/corporate_actions_overrides.csv', infer_schema_length=0)
dm = ca.filter(pl.col('action_type').is_in(['demerger', 'unparsed', 'other'])).select('symbol', 'ex_date', 'action_type', 'raw_purpose')
j = (u.join(dm, on='symbol').filter((pl.col('date') - pl.col('ex_date')).dt.total_days().abs() <= 3)
     .join(ov.select('symbol', pl.col('ex_date').str.to_date().alias('ov_date')), on='symbol', how='left')
     .filter(pl.col('ov_date').is_null() | ((pl.col('ov_date') - pl.col('ex_date')).dt.total_days().abs() > 3))
     .unique(['symbol', 'date']).sort('date'))
panel = pl.scan_parquet(DS / 'panel.parquet').filter(pl.col('symbol').is_in(j['symbol'].unique().to_list())).select(
    'date', 'symbol', 'series', 'open', 'close').collect().sort('symbol', 'date')
fil = nse_results.load(Path('data/raw/nse_results')).select('symbol', 'period_end', 'face_value')
pl.Config.set_tbl_rows(80); pl.Config.set_fmt_str_lengths(60); pl.Config.set_tbl_width_chars(220)
rows = []
for s, d, ratio, kind, txt in j.select('symbol', 'date', 'ratio', 'action_type', 'raw_purpose').iter_rows():
    p = panel.filter(pl.col('symbol') == s)
    cum = p.filter(pl.col('date') < d).tail(1)
    ex = p.filter(pl.col('date') == d)
    fv = fil.filter((pl.col('symbol') == s) & ((pl.col('period_end') - d).dt.total_days().abs() < 200))['face_value']
    rows.append((s, d, cum['date'][0] if cum.height else None, cum['close'][0] if cum.height else None,
                 ex['open'][0] if ex.height else None, ex['close'][0] if ex.height else None, round(ratio, 4),
                 fv.drop_nulls().mode()[0] if fv.drop_nulls().len() else None, kind, txt.strip()))
out = pl.DataFrame(rows, schema=['symbol', 'date', 'cum_date', 'cum_close', 'ex_open', 'ex_close', 'ratio', 'fv', 'kind',
                                 'purpose'], orient='row')
print(out.with_columns((pl.col('ex_open') / pl.col('cum_close')).round(6).alias('open_ratio')))
