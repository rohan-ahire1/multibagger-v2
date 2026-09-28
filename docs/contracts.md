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

Unexplained jumps are recorded, not fatal. The engine refuses a run whose trades hold through one (`engine/gate.py`, applied in `engine/run.py`).

## Signals (input to the engine)

One row per signal, made at the close of `signal_date`, on the adjusted price basis.

| Column | Meaning |
|---|---|
| `symbol`, `signal_date` | Who and when |
| `entry_ref` | Buy level. Fills from the symbol's next session if `open >= entry_ref` or `high >= entry_ref`, at `max(open, entry_ref)` |
| `stop` | Initial stop (adjusted basis). Risk per share = fill − stop |
| `size_mult` | Multiplies the risk budget (1.0 = normal) |

A signal waits `entry.pending_bars` of the symbol's own sessions; a missing bar does not use one up.

## Engine output (`engine/simulate.py`)

- `trades`: symbol, signal_date, entry_date, entry_price, stop, exit_date, exit_price, shares, return_pct, r_multiple, pnl,
  status, holding_days, mae_r, mfe_r, sector, entry_ref. Prices are net of slippage and charges. `status` is the exit
  reason (`intraday_stop`, `stopped`, `initial_stop_next_open`, `trail_ema_hybrid_next_open`, `stagnation_next_open`,
  `max_hold`, `drawdown_close`, `open`).
- `equity`: date, equity, cash, invested_value, open_positions, size_mult (equity uses raw closes).
- `skipped`: symbol, signal_date, status (why a signal never became a trade).
- Bars must start at `period.start` (EMAs are seeded from the first bar). Bars run to `period.end + settle_calendar_days`
  so late exits close; metrics use `[period.start, period.end]` and count trades by entry date.

## Baselines (`evaluation/baselines.py`)

`metrics.json` has `baselines.nifty500_tri_buy_and_hold` and `baselines.momentum_12_1`, measured over the run's period with the
same equity-curve metrics. Momentum: month-end 12-1 ranking, top `top_n` equal-weighted, next-open trades, market-profile
costs, no stops. A name with no open on a rebalance day is sold at its last close. Settings are in `configs/baselines.yaml`.
Full window 2010-01-04 to 2026-03-17: TRI 11.61% CAGR / 38.11% max DD; momentum 19.99% / 48.76%.

## Run record

See `PLAN.md` §6 (`src/mb/runs/record.py`). `manifest.json` carries `dataset_hash` (sha256 of the panel).
