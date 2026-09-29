# Handoff: v1 → v2

Written 2026-09-29 at the end of a long review of v1 (`~/projects/Multibagger`).
Read this, then `docs/PLAN.md`, before writing any code.

## 1. The short version

- v1 is an NSE daily swing-trading system built around Minervini's SEPA/VCP breakouts.
  It has good pieces (NSE data download, corporate-action handling, a careful simulator)
  but no single source of truth, and its headline results were wrong for months.
- **The trustworthy SEPA result is 6.39% CAGR / 23.55% max drawdown / 258 trades
  (2010-01-04 → 2026-03-17, after costs, idle cash earning 0%).** With idle cash earning
  6% it is 10.90%. Nifty 500 TRI returned about 11% a year over a similar period.
  So SEPA as currently defined does not beat the index.
- The 12–21% numbers in v1's docs came from a contaminated signal database (§5, trap 1).
  Do not quote them.
- The data is not the problem any more. NSE bhavcopy is the right research source and the
  price layer is now correct. Dhan's historical data is worse for research (§4.4).
- v2 is a new repo built to `docs/PLAN.md`. M0–M3 port proven v1 code; the first hard
  check is reproducing the 6.39% result trade-for-trade (§3).

## 2. Where everything is

### v1 code

| Item | Location |
|---|---|
| Repo | `~/projects/Multibagger` (GitHub: `rohan-ahire1/Multibagger`, private) |
| Branch with this session's fixes | `cleanup-live-prep`, local only, **not pushed** |
| Reference commit | `3f7cf7807b4b2318e3291bda5bea2870ff205710` |
| Python env | `uv` project, Python 3.12.13; run things with `uv run ...` from the repo root |

Commits on `cleanup-live-prep` (oldest first):

| Commit | What |
|---|---|
| `216e84e` | Add missing `tqdm` dependency |
| `02e4768` | Move superseded optimizers, sweeps, stale perf logs to `archive/` |
| `8c44e57` | `sepa update` refreshes NSE bhavcopy instead of yfinance (`live/nse_refresh.py`) |
| `cc61a71` | `optimize_joint_wf.py --funnel` signal-drop diagnostics (`lab/funnel.py`) |
| `ad0dfaa` | Refuse NSE rebuild when the zip archive is incomplete |
| `6945ea5` | CA fetch merges instead of overwriting; parser reads older split/bonus wording; `--reparse` |
| `ab0b2f5` | Simulator prices trades on the symbol-keyed sim layer; `--parity` data gate |
| `3f7cf78` | Price floor uses traded price (`raw_price`) on adjusted panels |

**Known wrong in that branch:** `docs/BACKTEST_TRUTH.md`, `AGENTS.md`, `CLAUDE.md`,
`GEMINI.md` and `tests/lab/test_sepa_parity.py` state 12.42% as the baseline. That number
uses the contaminated signal DB. v1 is now reference only; do not spend time fixing its docs.

### v1 data (all git-ignored, under `~/projects/Multibagger/data/`)

| Path | What | Use in v2 |
|---|---|---|
| `nse_bhavcopy_raw/` | 5,317 daily bhavcopy zips, 2005-01-03 → 2026-07-17 (360 MB) | **Raw source. Copy or re-point, never edit.** |
| `reference/nse_corporate_actions.parquet` | NSE CA feed, re-parsed with parser `2026.09.27.1`; last ex-date 2026-08-31 | Raw source |
| `reference/nse_corporate_actions_coverage.parquet` | Per-half-year fetch status | Raw source metadata |
| `reference/nifty500_tri_2010-01-04_2026-03-17.csv` | Benchmark TRI (ends 2026-03-17) | Baseline input |
| `reference/nifty500_price_2010-01-04_2026-07-24.csv` | Nifty 500 price index | Baseline input |
| `reference/full_sector_map.csv`, `nifty500_constituents.csv` | Sector map (symbol → sector) | Sector caps |
| `reference/security_master.parquet` | Identity reference | Identity layer |
| `nse_raw/ohlcv_raw.parquet` | Raw panel parsed from zips (8.35M rows, 4,453 symbols) | Rebuildable |
| `processed/`, `pit/` | Identity-tagged raw panels | Rebuildable |
| `adjusted/split_adjusted/`, `adjusted/total_return/`, `nse_adjusted/` | ISIN-keyed back-adjusted panels. **Buggy** (trap 3) | Do not use |
| `adjusted/sim_total_return/` | Symbol-keyed, CA matched to observed jumps, dividends included (241 MB) | Reference for v2's research panel |
| `db/sepa.duckdb` | **Contaminated** signal DB (union of scans from Mar–Jul) | Do not use |
| `db/sepa_PRE_CUTOVER_yfinance_20260719.duckdb` | Older yfinance-era DB | Do not use |
| `sim_scan/` | Clean full rescan on the sim layer. `pit` → `../adjusted/sim_total_return` symlink; `db/sepa.duckdb` has fresh signals | **The reference run** |
| `nse_rescan/` | Clean full rescan on raw `pit` prices | Comparison only |
| `dhan/` | Copy of the Dhan dataset from the VPS (parquet + reference, 468 MB) | Comparison only |
| `dhan_run/` | Dhan converted to v1 panel format + its own scan DB | Comparison only |
| `yf_adjusted/` | Legacy yfinance panel | Do not use |

`config/corporate_actions.csv` (tracked in v1 git) holds 452 curated CA overrides with
sources `manual`, `purpose_parsed`, `isin_corroborated`, `etf_inferred` (applied) and
`seed` (ignored). NIFTYBEES's 2019-12-19 1:10 split exists only here. Port this file.

### Reference files saved for v2 (`docs/reference/`)

| File | What |
|---|---|
| `v1_resolved_settings.json` | Every v1 setting as actually resolved at runtime (170 values in 23 sections), including values that only existed as code defaults. `runtime.data_dir` removed. This is the source for `strategies/sepa/configs/v1_port.yaml`. |
| `v1_reference_trades.csv` | The 258 filled trades of the reference run: symbol, signal/entry/exit dates, prices, stop, shares, return %, R, P&L |
| `v1_reference_metrics.json` | 6.39 / 23.55 / 0.27 / 258, window, commit, data dir |

### VPS

- `ssh server` (alias in `~/.ssh/config`, host 159.195.243.124, user `rohan`).
- `~/market-data/data/current/` — the Dhan dataset (release 2026-08-12). Built on another
  machine from `~/Documents/personal_projects/india-market-data` (not on this Mac).
- `~/projects/nse-market-collector/` — separate TypeScript project collecting Dhan intraday
  WebSocket snapshots. Unrelated to daily research; relevant only for a future intraday strategy.
- No Python `duckdb` installed on the VPS.
- `~/projects/multibagger-v2/` — the M6 paper job (`docs/paper.md`), uv in `~/.local/bin`, raw data copied from this Mac.
  The VPS clock is not IST; the timer names Asia/Kolkata.

### This Mac

- macOS ARM, 8 cores, 16 GB RAM.
- **Disk is 96% full (~20 GB free).** Do not duplicate the 5 GB data folder; point v2 at
  v1's raw folders or move them.
- NSE endpoints (bhavcopy archive and `api/corporates-corporateActions`) were reachable
  and tested working on 2026-09-27.

## 3. Reference numbers

All from v1's canonical harness, window 2010-01-04 → 2026-03-17, costs on
(10 bps slippage each side + statutory charges + DP fee), same config, data through 2026-07-17.

| Signals from | Prices for trades | CAGR | Max DD | Calmar | Trades | +6% idle cash |
|---|---|---|---|---|---|---|
| **Clean scan on sim layer (`data/sim_scan`)** | **sim layer** | **6.39%** | **23.55%** | **0.27** | **258** | **10.90%** |
| Clean scan on raw `pit` (`data/nse_rescan`) | sim layer | 4.73% | 20.08% | 0.24 | 217 | 9.57% |
| Clean scan on Dhan (`data/dhan_run`) | Dhan | 3.13% | 24.11% | 0.13 | 215 | 8.61% |
| Contaminated DB (`data/db`) | sim layer | 12.42% | 23.75% | 0.52 | 278 | 17.33% |
| Contaminated DB | raw `pit` (the 2026-08-26 state) | 6.61% | 35.18% | 0.19 | 283 | 10.21% |
| Contaminated DB | ISIN-keyed `nse_adjusted` | 22.11% | 21.54% | 1.03 | 280 | — |
| Contaminated DB, only stocks Dhan still lists | sim layer | 12.82% | 22.19% | 0.58 | 247 | — |

Reproduce the reference row in v1:

```bash
cd ~/projects/Multibagger && git checkout cleanup-live-prep
SEPA_DATA_DIR=$HOME/projects/Multibagger/data/sim_scan uv run python optimize_joint_wf.py --parity
# expect CAGR=6.39%  MaxDD=23.55%  Calmar=0.27  trades=258, DATA GATE: pass
```

Rebuilding the sim-layer scan from scratch (about 25 minutes):

```bash
# data/sim_scan/pit -> ../adjusted/sim_total_return ; fresh db initialised with DuckDbStore.initialize()
SEPA_DATA_DIR=$HOME/projects/Multibagger/data/sim_scan uv run python scripts/backfill_scans.py --start 2009-12-01 --end 2026-07-17
```

Rebuilding every price layer from the raw panel (about 35 seconds):

```bash
uv run python scripts/nse_build_adjusted_panel.py --dividends     # add --rebuild-raw to re-parse zips
```

## 4. What we know

### 4.1 The strategy (v1 committed config)

- Universe: NSE EQ series, traded price ≥ ₹50, 50-day average turnover ≥ ₹5 crore,
  50-day average volume ≥ 200k shares, ≥ 320 sessions of history, top 1,500 by turnover.
  Benchmark symbol NIFTYBEES.
- Trend template: close above SMA 50/150/200, SMA150 > SMA200, SMA50 > SMA150/200, SMA200
  rising over 21 sessions, ≥ 10% above 52-week low, within 45% of 52-week high.
- Relative strength: 63-day return rank; scanner needs rank ≥ 40, backtest needs ≥ 70.
- VCP setup: 65-session base, 10-day range ≤ 8%, volume dry-up, ATR contraction, ≤ 40%
  above SMA50, base depth ≤ 60%, contraction count ≤ 2.
- Breakout: close above pivot + buffer (0.3% or 0.5 ATR), volume ≥ 1x 50-day average,
  ≤ 30% extension.
- Signal filters in backtest: skip January signals, RS ≥ 70, quality gates
  (range10 ≤ 0.08, vol dry-up ≤ 0.9, fresh setup only, ≤ 2 contractions), top 20 per day.
- Entry: from the next session (D+1) within 8 symbol trading bars, at pivot buffer.
- Stop: max(structural stop, 7% cap). Exit: EMA hybrid (EMA21 after 3R, EMA10 after 5R),
  intraday hard stop, close-confirmed EMA exits fill next open, stagnation exit after
  15 bars below +0.4R, breakeven at 2R, max hold 150 days.
- Sizing: 2% risk per trade, max 20% per name, max 20 positions, max 4 per sector.
- Drawdown breaker: 50/60/70% — effectively off. v2's `v1_port.yaml` must keep these
  values to reproduce; change them only in a later config.
- Exact values: `docs/reference/v1_resolved_settings.json`. The v1 code also has
  settings-class defaults that differ from `config.yaml`; the JSON is what actually ran.

### 4.2 Shape of the result

- Average exposure about 40%; median 2 open positions; the 20-position cap is never hit.
  The binding constraint is signal supply, not settings.
- Win rate about 35%; returns are concentrated in a few big winners (in the contaminated
  run the top 19 trades were 83% of total R; re-measure on the reference run).
- Funnel measured on the contaminated DB (re-measure on the clean one in v2):
  quality gates removed about 70% of RS-qualified signals; each of the four gates was
  the sole blocker for 120–180 signals. Upstream, "close above SMA50" and "10-day range
  ≤ 8%" were the largest sole blockers.

### 4.3 NSE data

- Bhavcopy is the exchange's own daily file and includes delisted stocks. It is the
  research source.
- CA feed after re-parse: 673 splits, 672 bonuses, 30 bonus+split, 20,333 dividends,
  108 demergers, 19,436 unparsed (mostly board meetings/AGMs).
- Sim layer build (v1 `data_sources/sim_prices.py`): 1,340 share events matched to an
  observed jump, 26 too small to verify (applied on listed date), 2 duplicates dropped,
  135 unmatched (not applied). 1,139 unexplained session jumps > 1.5x remain across all
  4,453 symbols; **none fall inside any reference-run trade** (data gate passes).
  Reports: `reports/data_audit/sim_share_action_matches.csv`, `sim_unexplained_jumps.csv`.
- Benchmark TRI file stops at 2026-03-17; no automated fetch exists.
- Price data stops at 2026-07-17. `sepa update` in v1 can catch it up.

### 4.4 Dhan data

- Daily bars 2005-01-03 → 2026-08-11, 9,687 NSE equity instruments requested, data for 3,332.
- **Survivorship bias:** of 1,430 NSE securities that stopped trading, Dhan has 28; of 259
  liquid ones (> ₹5 cr average turnover), 4. DHFL, JETAIRWAYS, SINTEX, merged PSU banks
  and HDFC are missing.
- **Prices are split/bonus adjusted but volume is not.** Turnover computed as
  price × volume is therefore understated before splits, which wrongly shrinks the universe.
- Where both have data, daily returns agree within 0.5% on 99.6% of 4.9M stock-days.
  About 200 symbols disagree by > 20% on some days (TCI, KPIT, ASIANTILES, ARVIND in 2011).
  Dhan is missing about 46,500 sessions on shared stocks.
- Conclusion: use Dhan for live orders and intraday, not for daily research.

## 5. Traps found (and how v2 avoids each)

1. **Accumulating signal database.** v1's scanner upserts signals into DuckDB and never
   clears rows a later scan no longer produces. `data/db/sepa.duckdb` is the union of
   full rescans from 2026-03-21, 04-18, 07-18 and 07-22 across different code and data
   versions (62% of its breakouts match yfinance prices). In the backtest window it holds
   1,862 breakouts; a clean scan produces 725. Every v1 headline number since March used it.
   → v2: signals are computed inside each run and stored only in that run's record.
2. **Simulator on raw prices.** Commit `0ff0c3a` (2026-08-26) changed `panel_subdir` to the
   raw `pit` panel for everything, so splits were booked as crashes (BAJFINANCE 2016 −8.7R,
   APLAPOLLO −13.4R, IGL −23.8R).
   → v2: engine always prices on `adj_*` columns (PLAN §4.3).
3. **ISIN-keyed adjustment.** A face-value split changes the ISIN, so an ISIN-keyed
   back-adjustment misses one side (BAJFINANCE 2025 split+bonus never applied). An override
   dated to the observed jump (2016-09-07) plus the feed row on the listed date (2016-09-08)
   applied the same 10x twice, producing one fake +99.5R trade.
   → v2: port the symbol-keyed matcher (`sim_prices.py`), not `adjustment.apply_adjustment`.
4. **Absolute levels on adjusted prices.** A ₹50 price floor on back-adjusted prices removes
   stocks that later split (usually past winners).
   → v2: level filters use raw columns; ratios and indicators use adjusted ones.
5. **Hidden defaults.** v1 `settings.py` defaults differ from `config.yaml` (drawdown breaker
   0.15/0.25/0.35 in code vs 0.50/0.60/0.70 in config; risk per trade 3.5% vs 2%).
   → v2: no defaults, unknown keys fail.
6. **Inflated CLI metric.** `sepa backtest` reports a serial-R-compounded CAGR that
   overstates results. Only the equity-curve CAGR is valid.
   → v2: one metrics module.
7. **CA fetch overwrote history.** Fetching one year replaced the whole file. Fixed in
   `6945ea5`; port the merge behaviour.
8. **Dividend prev_close.** v1's `_load_ca` joins the dividend's "previous close" with a
   backward as-of join on the ex-date itself, so it uses the ex-date close when that day
   traded. `sim_prices.dividend_steps` uses the last close strictly before the ex-date.
   Port the latter.
9. **Signal price rescaling.** v1 `load_inputs` rescales each signal's entry/stop/pivot by
   `ohlcv_close / signal_close` on the signal date so signals scanned on one price basis
   work on another. In v2 signals and engine read the same research panel, so this step
   should disappear; if it is needed, something is inconsistent.
10. **Repeatedly reused test periods.** v1's "2023+ holdout" was used to judge many
    changes, so it is no longer a fair test. v2's locked period starts fresh.

## 6. Porting guide

Port each piece with tests before moving on. Do not port anything not listed.

| Piece | v1 source | Notes |
|---|---|---|
| Trading calendar | `calendar.py` | v1 treats every weekday as a trading day; use the NSE holiday list or the set of dates present in bhavcopy |
| Bhavcopy download | `data_sources/nse_bhavcopy.py` (`NseBhavcopyClient`) | Two URL formats (legacy before a cutoff date, new after); polite 0.4 s sleep; 404 = holiday or not yet published |
| Bhavcopy parsing | `storage/bhav_raw_store.py` (`parse_zip`) | Keeps series EQ and BE; unique on (date, symbol) |
| CA fetch + parser | `scripts/nse_corporate_actions_fetch.py` | Bootstrap the NSE session first; fetch in half-year windows; merge by window; keep `original_source_text` |
| CA multipliers | `data_sources/adjustment.py` (`event_price_multiplier`) | Split m = new_fv/old_fv; bonus a:b m = b/(a+b); combined multiplies |
| CA overrides | `config/corporate_actions.csv` | Only sources `manual`, `purpose_parsed`, `isin_corroborated`, `etf_inferred` |
| Identity | `data_sources/security_identity.py`, `data_sources/pit.py` | ISIN-based `security_id`, `fallback:` when missing |
| Research panel | `data_sources/sim_prices.py` | Symbol-keyed; ±3-session jump matching, tolerance 1.25x, min detectable 1.2x, unexplained jump threshold 1.5x — all of these become data-config values |
| Indicators | `indicators/` | SMA, ATR, RS, contraction, tightness, highs/lows, volume |
| SEPA signals | `strategy/signal_engine.py`, `trend_template.py`, `vcp_setup.py`, `ranking.py` | Remove the pullback branch (disabled in v1). Keep fail masks for the funnel |
| Simulator | `lab/engines/portfolio_sim.py` (`simulate_portfolio_python`, `filter_signals`) and `backtest/exit_engine.py` | Large file with many modes; port only the modes the committed config uses (`baseline_ema_hybrid`, `intraday_hard`, `next_open`, stagnation exit) |
| Costs | charges inside `portfolio_sim.py` | Move every rate to `configs/market/nse_cash.yaml` |
| Metrics | `optimize_joint_wf.py::_metrics`, `lab/metrics.py` | Equity-curve CAGR, max DD, Calmar |
| Funnel | `lab/funnel.py` | Sole-blocker counting |
| Paper sheet | `scripts/sepa_paper_daily.py` | ENTER/EXIT/HOLD tickets, staleness guard |
| Daily refresh | `live/nse_refresh.py` | Download missing zips; refuse rebuild if zips < panel sessions |

**Parity target for M3:** `strategies/sepa/configs/v1_port.yaml` on the ported research
panel must reproduce `docs/reference/v1_reference_trades.csv` trade-for-trade (same symbols,
entry dates and exit dates) and 6.39 / 23.55 / 0.27 / 258. Small price differences in the
last decimal are acceptable; any different trade is not. Diff trade lists, not just totals.

## 7. Decisions (defaults assumed unless the user changes them)

1. Repo name: `multibagger-v2`.
2. Locked final test period: from 2024-01-01.
3. Research on the Mac; daily jobs on the VPS.
4. Dashboard: generated HTML report per day first.
5. Stack: Python 3.12, `uv`, Polars, Pydantic v2 (strict), Typer CLI, Parquet + JSON for
   datasets and run records. No DuckDB for signals.

## 8. Working with this user

- Keep answers short and plain. Lead with the result. Explain any jargon briefly.
- When a decision is needed, list the options and give a recommendation.
- Never add AI attribution (co-author lines, session links) to commit messages.
- Branch before committing; do not push without asking.
- The user has been frustrated by getting different numbers from different agents.
  Every reported number must come with its run id and config file, and be reproducible.
- Model split agreed: Sonnet for M0–M3 (porting against this spec), Opus for M4–M5
  (strategy research) and for reviewing ports.

## 9. First steps for the next session (M0)

1. `git init` in `~/projects/multibagger-v2` and create the layout in PLAN §9.
2. `uv init` with Python 3.12; add polars, pydantic, typer, pyyaml, pyarrow, pytest.
3. Write `AGENTS.md`: layer map, where configs live, the CLI commands, and the rules
   (no values in code, no scripts, rebuild-not-append, run records for every number).
4. Strict config loader: Pydantic models with `extra="forbid"` and no defaults; loads
   `configs/market/*.yaml` and a strategy config; saves the resolved config.
5. Run record writer: `runs/<run_id>/` with `config.resolved.yaml`, `manifest.json`
   (git commit, config hash, dataset version), `metrics.json`.
6. CLI shell (`mb`) with `backtest` wired to a dummy strategy that emits no trades.
7. Exit check: a dummy run writes a complete run record, and a config with an unknown or
   missing key fails with a clear error.
8. Then M1: point the NSE adapter at `~/projects/Multibagger/data/nse_bhavcopy_raw/`
   (read-only) instead of re-downloading 5,317 files.
