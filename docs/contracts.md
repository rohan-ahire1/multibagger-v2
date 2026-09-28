# Contracts

## Canonical bars (`sources/nse_bhavcopy.py` output)

One row per `(symbol, date)`: `date, symbol, security_id, series, open, high, low, close, volume, turnover, source`.
Prices and volume are as traded (unadjusted). `security_id` is `isin:<ISIN>`, else `fallback:<symbol>:<series>`.

## Research panel (`data/adjust.py`, stored as `panel.parquet`)

Canonical bars plus `adj_open, adj_high, adj_low, adj_close, adj_volume, adj_factor`. Adjustment is keyed by symbol.
Each split/bonus is matched to the session where the price jumped (±3 sessions of the listed ex-date); dividends give a
total-return price adjustment (price only, not volume). Strategies: ratios and indicators use `adj_*`; absolute levels
(min price, min ₹ turnover) use the raw columns.

## Dataset version (`data/datasets/<name>/<version>/`)

`panel.parquet`, `ca_matches.parquet` (status per share action: matched / applied_small / duplicate / unmatched / no_prices),
`unexplained_jumps.parquet` (adjusted moves beyond the configured ratio), `unusable_actions.parquet`, `manifest.json`
(input hashes, config hash, code commit, check results, output hashes). Versions are immutable and rebuild byte-identically.

Unexplained jumps are recorded, not fatal. The engine must refuse a run whose trades hold through one (v1 "data gate";
lands with M2/M3).

## Signals, run record

Run record: see `PLAN.md` §6 (`src/mb/runs/record.py`). Signals: added in M3.
