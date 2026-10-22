# Autonomous research loop (started 2026-10-23)

The user asked for an endless loop on the VPS, with no input from them: research on the internet what could improve
the adopted swing book, implement it, test it, keep it if it passes, otherwise try the next idea. Never stop.

## The book being improved

- Adopted book (paper since 2026-10-30): pin `momentum/m106_g25_jr_gap`, paper config
  `configs/paper/momentum_b_top25_gold25_jr_gap.yaml`. Month-end momentum, top 25 NSE stocks (₹2cr ADV floor,
  delivery filter), 25% GOLDBEES fixed, half the stock share to GOLDBEES when JUNIORBEES < its 200-day SMA, gap rule.
  Dev 2010-23: 30.1% CAGR / 20.1% DD / Calmar 1.500. Locked 2024-01..2026-09 (spent in M107): 20.4% / 15.5% / 1.314.
- Everything tried so far: `docs/research/calmar-search.md` (M1-M107 table) and `docs/research/m108.md`..`m119.md`.
  Read them before choosing an idea. Do not retry a dead family without a new reason written in the pre-registration.
  Dead since M107: tax-timing and tax-loss harvesting (M110, M113), insider buys/sells (M111, M112), results reaction
  (M114), wider hold buffer (M115), bulk/block deals (M116), rebalance day / sell-in-May (M117), FII futures, VRP,
  put-call ratio (M118), F&O option-signal book and blends (M119), momentum index fund, MWPL crowding, HY spread.
  Also earlier: stops on this book, book-level stops, vol targeting, low-vol sleeve, 52w-high, residual momentum,
  frog-in-the-pan, Optuna tuning (overfits), VCP.

## The bar (set 2026-10-04; do not loosen it)

A change is adopted only if, against M106 on the newest research dataset:
1. it beats M106 on Calmar before AND after tax (`src/mb/evaluation/tax.py`) at decision offset 0, AND before tax at
   offsets 5, 10 and 15 (refs `m111_ref_offN`); offset luck alone is ±0.2 Calmar, so offset-0-only wins are noise;
2. it does not lose a development fold (f1/f2/f3 in `configs/baselines.yaml`);
3. it still beats M106 at 25 bps extra slippage;
4. robustness (information, but a fail blocks adoption): neighbouring parameter values do not collapse; block bootstrap
   Calmar above M106 in ≥ 85% of resamples.
The locked window 2024+ was used for M107 and peeked at again in M112; treat any later look at it as weak evidence
only, and never pass `--final` on a new config without writing why first. Keep a running count of variants tried
(for the deflated Sharpe check, M104); report it in every result.

## One cycle

1. Read `docs/research/loop-journal.md` (newest at the bottom) to see what the last cycles did and what is queued.
2. Research: search the web hard (WebSearch extended, SSRN, arXiv, NBER, journals, practitioner blogs, India-specific
   work on NSE momentum, smallcase/PMS methodology notes, Indian tax and cost rules). Look for ideas with real
   evidence, preferably out-of-sample or on emerging markets / India. Write the candidates and their sources into the
   journal, pick the most promising untried one. Ideas need only data we have or can fetch free (NSE archives,
   `data/raw/*`, india-market-data on the Mac is not reachable; fetch on the VPS).
3. Pre-register in `docs/research/mNNN.md` (next free number, from 120): idea, source, exact rule, configs, the bar,
   what would count as a fail. Commit it before running any backtest.
4. Implement per `AGENTS.md`/`CLAUDE.md` (configs not code values, tests, no scripts/ folder, notebooks for one-offs).
   Run `uv run pytest` for touched areas.
5. Test against the bar. Record run ids. Write results and verdict into `mNNN.md`, add a row to `calmar-search.md`.
6. Commit on branch `research` (new branches `mNNN-<slug>` off it are fine) and push to origin. No AI attribution in
   commit messages. Never push to `m8` or `main` except for step 7.
7. Only if a change passes the whole bar: write a NEW paper config + units for it next to the running books (start =
   next month-end), merge to `m8`, push, `git pull` in `~/projects/multibagger-v2`, install the timer. Never edit, stop
   or restart the existing paper books or their configs. If installing is blocked, write the exact command into the
   journal and the ntfy message.
8. Append to `docs/research/loop-journal.md`: date, idea, sources, result, verdict, variants count, next ideas queue.
9. Send one plain-language line to ntfy: `curl -s -d "<msg>" https://ntfy.sh/$TOPIC` with TOPIC from
   `~/.config/multibagger/alerts.env` (never print the topic or any secret into the repo).
10. Start the next cycle. If an idea fails, pick another. If ideas run thin, do data-quality work, realism (costs,
    circuit locks, live fills), robustness of M106 itself, or live-trading (M7, Dhan) preparation, rather than
    stopping. Never end because work seems "done".

## Machine rules (VPS: 4 cores, 7 GB RAM, shared)

- Work in `~/projects/mb-research` only. `~/projects/multibagger-v2` is the live paper deployment: read-only except
  step 7.
- Paper jobs run Mon-Fri 19:45-20:00 and 23:15-23:30 IST and take up to 2 GB. Do not start heavy backtests in those
  windows. Run backtests with `nice -n 15`. No large Optuna sweeps (they overfit and the box is small).
- Keep at least 20 GB free disk. Do not touch the Dhan token, the collector, spread-rec or paper-alert timers.
- Dataset: newest `data/datasets/nse_research/*` (2026-10-14 at start). New datasets go through `mb data build`.
