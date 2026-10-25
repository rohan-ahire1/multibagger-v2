"""M141 information: parse coverage of the fetched quarterly results by year (no returns).

Usage: uv run python notebooks/m141_coverage.py [raw_dir]
"""
import sys
from pathlib import Path

import polars as pl

from mb.sources import nse_results

raw = Path(sys.argv[1] if len(sys.argv) > 1 else 'data/raw/nse_results')
df = nse_results.load(raw)
pl.Config.set_tbl_rows(40)
print(df.height, 'filings,', df['symbol'].n_unique(), 'symbols')
print(df.with_columns(pl.col('period_end').dt.year().alias('year')).group_by('year').agg(
    pl.len().alias('filings'), pl.col('symbol').n_unique().alias('symbols'),
    pl.col('net_profit').is_not_null().mean().round(3).alias('np_ok'),
    pl.col('sales').is_not_null().mean().round(3).alias('sales_ok'),
    pl.col('eps').is_not_null().mean().round(3).alias('eps_ok')).sort('year'))
