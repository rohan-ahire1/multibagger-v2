# M6: paper trading

The M5 final strategy (`strategies/momentum/configs/voladj_final.yaml`, pinned by hash in
`configs/paper/momentum_voladj.yaml`) runs as a paper book on the VPS from the 2026-09-30 close with ₹10L.

## What runs

`mb paper daily configs/paper/momentum_voladj.yaml`, from the systemd user timer in `deploy/` (Mon–Fri 19:45 and
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

## Files (VPS, `~/projects/multibagger-v2/data/paper/momentum_voladj/`)

| Path | What |
|---|---|
| `book.json` | Cash, positions, pending orders, last committed session |
| `days/<session>.json` | Everything done in that session, with the dataset version and panel hash it used |
| `tickets/<session>.md` | Month-end orders as a readable list (what M7 would place) |
| `replays/<session>.md` | Replay result |
| `daily/<date>-<time>.json` | Log of each run: downloads, build, problems |

`mb paper status configs/paper/momentum_voladj.yaml` prints the book and the latest replay.
Logs: `journalctl --user -u mb-paper`.

## When an alert says the book stopped

A session with an unexplained price jump on a held or picked name is not committed; the book waits at the session
before it and every run retries. Find the event on NSE, then either add the missing split, bonus or demerger to
`configs/data/corporate_actions_overrides.csv`, or, if the move was real, add it to `configs/data/verified_price_moves.csv`
with a reason and source. Commit, pull on the VPS, and the next run rebuilds the dataset and continues.

"Stale data" means the newest bhavcopy is more than one trading day old: check the NSE archive and the job log.
