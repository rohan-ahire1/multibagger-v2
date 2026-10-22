"""M134 information (no returns): share of a run's new buys with a promoter pledge event broadcast in the days before.

Usage: uv run python notebooks/m134_pledges.py RUN_ID [LOOKBACK_DAYS]
Counts a buy (trades.parquet entry) as flagged when its symbol had a creation / invocation event (any size) broadcast
in (entry_date - lookback, entry_date). Fund units excluded. By period, from 2015 (first full window).
"""
import sys
from datetime import timedelta
from pathlib import Path

import polars as pl

from mb.sources import nse_pledges


def main(run: str, lookback: int) -> None:
    ev = nse_pledges.load(Path('data/raw/nse_pledges'))
    t = (pl.read_parquet(Path('runs') / run / 'trades.parquet')
         .filter(~pl.col('symbol').is_in(['GOLDBEES', 'JUNIORBEES', 'NIFTYBEES']))
         .filter(pl.col('entry_date') >= pl.date(2015, 1, 1)).select('symbol', 'entry_date').unique())
    for kinds in (['creation', 'invocation'], ['creation'], ['invocation']):
        e = ev.filter(pl.col('kind').is_in(kinds)).select('symbol', 'avail')
        j = t.join(e, on='symbol', how='left').with_columns(
            ((pl.col('avail') < pl.col('entry_date'))
             & (pl.col('avail') >= pl.col('entry_date') - timedelta(days=lookback))).fill_null(False).alias('hit'))
        f = j.group_by('symbol', 'entry_date').agg(pl.col('hit').any())
        by = (f.with_columns(pl.col('entry_date').dt.year().alias('y'))
              .group_by(pl.when(pl.col('y') <= 2017).then(pl.lit('2015-17')).when(pl.col('y') <= 2020)
                        .then(pl.lit('2018-20')).otherwise(pl.lit('2021-23+')).alias('period'))
              .agg(pl.len().alias('buys'), pl.col('hit').sum().alias('flagged')).sort('period'))
        print(kinds, f'flagged {f["hit"].sum()} of {f.height} buys')
        print(by)


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 180)
