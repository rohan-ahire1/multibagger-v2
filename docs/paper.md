# M6: paper trading

Two paper books run on the VPS from the 2026-09-30 close, ₹10L each, stocks only:

- `configs/paper/momentum_voladj_stocks.yaml`: the M5 final strategy's params (`voladj_final.yaml`, 30 names) with fund
  units excluded, pinned by hash through `strategies/momentum/configs/voladj_stocks_dev_d.yaml`.
- `configs/paper/momentum_top40_stocks.yaml`: the M8 40-name variant (`docs/research/m8.md`) with fund units excluded,
  through `m8_top40_stocks_dev_d.yaml`. It has no final run; this book is its test.

Each book has its own files, units and alerts (titled by book name). `deploy/mb-paper-top40.*` runs the second book five
minutes after the first. Both jobs take the same lock, so they never download or build the shared daily dataset at the
same time. The book refuses M8 options it cannot trade yet (second lookback, sector cap, no-resize, volatility target).

## Stocks only (changed before the start)

The first books, `momentum_voladj.yaml` and `momentum_top40.yaml`, were retired on 2026-09-29 before their first session.
Their strategy configs have `exclude_fund_units: false`, and the vol-adjusted score (return over volatility) ranks liquid
and money-market ETFs first because they barely move: at the 2026-09-28 close, 8 of the 30 picks and 9 of the 40 were
fund units, holding near-cash returns in stock slots. The replacements differ only in `exclude_fund_units: true`
(ISINs starting INF are dropped). Dev period, dataset `nse_research@2026-09-29d`:

| Config | Run | CAGR % | Max DD % | Calmar | f1 | f2 | f3 |
|---|---|---|---|---|---|---|---|
| `m8_control_dev_d` (voladj, funds allowed) | 20260929-065259-99baaabb | 25.23 | 40.38 | 0.625 | 0.279 | 1.600 | 0.696 |
| `voladj_stocks_dev_d` | 20260929-074906-afd6d499 | 25.51 | 39.77 | 0.641 | 0.273 | 1.600 | 0.727 |
| `m8_top40_dev_d` (funds allowed) | 20260929-065335-1df714a6 | 25.11 | 38.79 | 0.647 | 0.308 | 1.705 | 0.701 |
| `m8_top40_stocks_dev_d` | 20260929-074916-cd4d9211 | 25.12 | 38.79 | 0.648 | 0.288 | 1.706 | 0.713 |

Both stock-only configs beat the 12-1 baseline and the Nifty 500 TRI on Calmar in every fold and over the whole period.
The funds-allowed voladj_final run held fund units in a few earlier years and most often in 2025. This was a
fix to what the book can hold, chosen before any paper result, not a tuned variant.

## What runs

`mb paper daily configs/paper/momentum_voladj_stocks.yaml`, from the systemd user timer in `deploy/` (Mon–Fri 19:45 and
23:15 IST):

1. Download the holiday list, new bhavcopy zips and this year's corporate actions into `data/raw/`.
2. Build a new `nse_daily` dataset version if any input changed (label = last session). Old versions beyond
   `keep_datasets` are deleted. `nse_daily` has the same rules as `nse_research`; only the check limits allow for growth.
3. Advance the book one session at a time (`src/mb/live/paper.py`): corporate actions on held names, fills at the open,
   marks at the close, and at a month-end close whole-share orders for the next open.
4. Replay: the backtest over [start, book date] on the same dataset. Month-end picks must match exactly and equity
   must stay within `replay_max_equity_gap_pct` (whole shares and cash make a small gap normal).
5. Alerts through ntfy (topic in `~/.config/multibagger/alerts.env`): month-end orders, a weekly "ok" on Fridays,
   and a high-priority alert for any problem or crash. Silence for more than a week means the job is not running.

Running it twice a day, or re-running after a fix, is safe: each session is committed once.

## Symbol renames (M14)

When a company changes its NSE symbol (same ISIN), `nse_daily` ends the old symbol and starts the new one with no
history. A held name then gets no bars ("held, no trade" notes) and is sold at its last close at the next month-end,
and the new symbol cannot be ranked for about a year. The two running books keep this behaviour, which matches their
backtest references (`docs/research/m14.md`). The undeployed inverse-vol draft (`momentum_top40_invvol.yaml`) reads
`configs/data/nse_daily_linked.yaml` instead: the old symbol's bars carry the new symbol, and the book moves a position
bought (and orders decided) under the old symbol to the new one before that session's corporate actions (a `rename`
entry in the day's `corporate_actions`). Replay maps recorded picks the same way. Built locally at the 2026-09-28 close,
the linked daily data has 199 links since 2023 (HEG → HEGAM on 2026-09-22 is the newest), the same 144 unexplained
jumps as `nse_daily`, and the same picks for all three books at that close.

## Delivery data (M43)

The M40 pin drops the eligible names with the lowest delivery share, so its book needs NSE's daily delivery file.
`configs/data/nse_daily_delivery.yaml` is the linked daily data plus a `delivery` section: the daily job downloads
the delivery file for any build session that lacks one (NSE can publish it after the bhavcopy; the share skips the last
21 sessions, so a late file never moves a decision), and a new file triggers a rebuild. The undeployed draft
`momentum_top40_gold_deliv.yaml` reads it. On the Mac, run over Feb–Jul 2026 from a scratch store, its six decisions
equal the pin's targets on the research data and the replay passes (see `docs/research/m43.md`).

## Files (VPS, `~/projects/multibagger-v2/data/paper/<book name>/`)

| Path | What |
|---|---|
| `book.json` | Cash, positions, pending orders, last committed session |
| `days/<session>.json` | Everything done in that session, with the dataset version and panel hash it used |
| `tickets/<session>.md` | Month-end orders as a readable list (what M7 would place) |
| `replays/<session>.md` | Replay result |
| `daily/<date>-<time>.json` | Log of each run: downloads, build, problems |

`mb paper status configs/paper/momentum_voladj_stocks.yaml` prints the book and the latest replay.
Logs: `journalctl --user -u mb-paper`.

## When an alert says the book stopped

A session with an unexplained price jump on a held or picked name is not committed; the book waits at the session
before it and every run retries. Find the event on NSE, then either add the missing split, bonus or demerger to
`configs/data/corporate_actions_overrides.csv`, or, if the move was real, add it to `configs/data/verified_price_moves.csv`
with a reason and source. Commit, pull on the VPS, and the next run rebuilds the dataset and continues.

"Stale data" means the newest bhavcopy is more than one trading day old: check the NSE archive and the job log.
