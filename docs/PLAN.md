# Multibagger v2 — Plan

Status: draft for review · 2026-09-28 · Context, reference numbers and data locations: `docs/HANDOFF.md`

## 1. Goal

Build a trading system for NSE cash equities that is simple enough for a person
or an agent to understand in minutes, gives the same result every time it is
run, and can be deployed with real money once a strategy earns it.

"Deployable" means all of these are true:

1. One command rebuilds all data from raw sources, and the result is identical every time.
2. One command backtests any strategy config, and the result is identical every time.
3. Every reported number can be traced to the exact data, code and config that produced it.
4. The strategy beats the baselines (Nifty 500 TRI and simple momentum) on a
   locked final test period, after costs.
5. Paper trading has run daily for at least 3 months, and its trades match what
   the backtest would have done on the same days.
6. Live trading has safety rails: position caps, a working drawdown breaker, a
   kill switch, and alerts for stale or suspicious data.

## 2. What went wrong in v1 (and the rule each one produced)

| What happened in v1 | Rule in v2 |
|---|---|
| Signal database kept every past scan, so backtests traded ~3x more signals than the strategy produces. The 12–21% results came from this. | Derived data is rebuilt, never appended to (§4.2). |
| The same setting had one value in code and another in the config (drawdown breaker 15/25/35% vs 50/60/70%). | No defaults in code. Missing or unknown settings are errors (§5). |
| Several backtest engines and a CLI metric that inflated returns; agents got different numbers. | One engine, one metrics module (§4.5). |
| A data-source switch on 2026-08-26 silently halved the result. | Every run records its data version and config hash; results are compared to the pinned baseline automatically (§6). |
| A split applied twice (BAJFINANCE 2016) produced one fake +99R trade. | Data checks run on every build and fail loudly (§4.3). |
| 50+ loose scripts; each agent picked a different one. | One CLI. No scripts outside it (§8). |
| Past test periods were reused so often they stopped being fair tests. | A locked final test period enforced by the tools (§7). |

## 3. Principles

1. **One home per fact.** Every parameter, rule and threshold lives in exactly one config file. Code contains logic, never values.
2. **Layers talk through contracts.** Data, cleaning, strategy, engine and evaluation only exchange data in documented formats. Any layer can be swapped without touching the others.
3. **Raw is immutable; everything else is rebuilt.** Downloads are never edited. Everything downstream is regenerated from them.
4. **Every result is reproducible.** A run records data version, code commit and the fully resolved config.
5. **Always compared.** Every backtest report shows the baselines next to the strategy.
6. **Backtest, paper and live share one code path.**
7. **Fail loudly.** Missing data, unexplained price jumps, unknown config keys and parity drift stop the run.
8. **Small and obvious.** Prefer deleting to archiving. A new agent should find anything from `AGENTS.md` in under a minute.

## 4. Architecture

```
sources ──► raw store ──► canonical bars ──► research panel ──► strategy ──► engine ──► evaluation
 (NSE,        (immutable     (one standard     (adjusted +          (signals or   (fills, stops,  (metrics,
  Dhan...)     downloads)     format)           raw columns,         target        equity,         baselines,
                                                universe)            weights)      trades)         reports)
                                                                                        │
                                                                         paper / live ◄─┘ (same engine, broker adapter)
```

### 4.1 Sources (adapters)

Each source is an adapter that downloads into the raw store and converts to
**canonical bars**. Adding a source means writing one adapter; nothing else changes.

| Adapter | Used for | Notes |
|---|---|---|
| `nse_bhavcopy` | Research and daily prices | Exchange's own file; includes delisted stocks. Primary. |
| `nse_corporate_actions` | Splits, bonuses, dividends | Merged fetch, never overwrite. |
| `niftyindices` | Benchmarks (Nifty 500 TRI and price) | Manual CSV import is acceptable. |
| `dhan` | Live orders; intraday later | Not for research: missing delisted stocks, volume not split-adjusted. |

### 4.2 Data stores

- `data/raw/<source>/...` — downloads exactly as received. Never modified.
- `data/datasets/<name>/<version>/` — built outputs. A version is immutable and has a
  `manifest.json` (inputs, their hashes, build config, code commit, row counts, check results).
- A strategy config names the dataset version it runs on. "Latest" is not allowed in a
  pinned config.
- Signals are not stored across runs. They are computed per run and saved inside that run's record.

### 4.3 Canonical bars (the data contract)

One row per `(symbol, date)`. Every adapter must produce exactly this:

| Column | Type | Meaning |
|---|---|---|
| `date` | date | Trading session |
| `symbol` | str | NSE ticker as traded that day |
| `security_id` | str | Stable identity (ISIN-based, with fallback) |
| `series` | str | EQ, BE, … |
| `open`,`high`,`low`,`close` | float | Traded prices, unadjusted |
| `volume` | int | Shares, unadjusted |
| `turnover` | float | ₹ traded |
| `source` | str | Adapter name |

**Research panel** = canonical bars plus adjusted columns, built by the cleaning layer:

| Extra column | Meaning |
|---|---|
| `adj_open`…`adj_close`, `adj_volume` | Continuous across splits, bonuses (and dividends for total return), keyed by symbol, each action matched to the session where the price jumped |
| `adj_factor` | Multiplier applied to that row |

Rule for strategies: **ratios and indicators use `adj_*`; absolute levels (min price,
min ₹ turnover) use the raw columns.** This is point-in-time safe.

**Checks on every build** (a failure blocks the version from being used):
missing sessions vs NSE calendar, duplicate keys, non-positive prices, unexplained
session-to-session jumps beyond 1.5x in adjusted prices, corporate actions that did not
match a price jump, row-count drift vs previous version.

### 4.4 Strategy layer

A strategy is a folder with code plus one or more config files. Two kinds, one interface each:

- **Signal strategy** (e.g. SEPA): `signals(panel, params) -> signals` where each signal has
  symbol, date, entry reference, initial stop, rank score.
- **Rebalance strategy** (e.g. momentum): `targets(panel, params, date) -> {symbol: weight}` on rebalance dates.

Strategies do not size positions, apply costs, or touch the broker. They only decide
*what* and *when*.

### 4.5 Engine

One simulator for all strategies. It owns: order timing (next open, never same bar),
fills with slippage, stops and exits (rules come from the strategy config), position
sizing, portfolio caps, drawdown breaker, costs from the market profile, idle-cash
yield from the market profile, corporate-action-safe pricing (uses `adj_*`).

Metrics live in one module: CAGR and max drawdown from the daily equity curve,
Calmar, exposure, turnover, trade stats, R distribution, concentration of returns.

### 4.6 Evaluation

Every run report contains, side by side: the strategy, Nifty 500 TRI buy-and-hold, and
simple 12-1 momentum, on the same dates and costs. Plus fold results and, only in a
final evaluation, the locked period (§7).

### 4.7 Paper and live

A daily job (VPS, after close): update data → build new dataset version → run checks →
compute signals → engine produces tomorrow's orders → paper book or broker adapter.

The Dhan broker adapter places entries, places exchange-side stop orders (GTT), and
reconciles actual holdings against the engine's expected book every day. Any mismatch
stops new orders and alerts.

## 5. Configuration

**Format:** YAML, loaded into strict Pydantic models. No field has a default in code.
Unknown keys are errors. The fully resolved config is saved in every run.

**Files:**

```
configs/
  market/nse_cash.yaml          # costs, slippage, STT, DP fee, idle-cash yield, trading calendar
  data/nse_research.yaml        # which adapters, cleaning rules, check thresholds
  baselines.yaml                # benchmark definitions
strategies/
  sepa/
    strategy.py                 # logic only
    configs/
      v1_port.yaml              # v1 rules reproduced exactly (the reference)
      2026-10_baseline.yaml     # a milestone
      candidate_wider_universe.yaml
  momentum/
    strategy.py
    configs/...
```

**A strategy config has every value the strategy and engine need:**

```yaml
name: sepa
version: 2026-10_baseline
dataset: nse_research@2026-09-28      # pinned
market: nse_cash
period: {start: 2010-01-04, end: 2023-12-31}   # never past the lock date unless final eval
universe:
  series: [EQ]
  min_price_inr: 50                   # uses raw close
  min_adv50_inr: 50_000_000           # uses raw turnover
  min_history_days: 320
signals:
  trend_template: {sma_fast: 50, sma_mid: 150, sma_slow: 200, ...}
  vcp: {...}
  breakout: {volume_mult: 1.0, max_extension_pct: 0.30}
  quality: {range10_max: 0.08, voldry_max: 0.9, setup_streak_max: 0, contraction_max: 2}
  skip_months: [1]
entry: {timing: next_open, pending_bars: 8, buffer_atr_mult: 0.5}
exits: {max_loss_pct: 0.07, mode: ema_hybrid, tighten_r: 5.0, stagnation_bars: 15, ...}
sizing: {risk_per_trade: 0.02, max_name_pct: 0.20, max_positions: 20, max_sector_positions: 4}
risk: {drawdown_half: 0.15, drawdown_stop: 0.25, drawdown_close: 0.35}
```

Milestones are just config files plus the run records they produced. A config that has
been used for a pinned result is never edited; changes go in a new file.

## 6. Run records

Every backtest writes `runs/<run_id>/`:

```
config.resolved.yaml     # every value used
manifest.json            # dataset version + hash, code commit, config hash, start/end, host, duration
metrics.json             # strategy and baselines
trades.parquet
equity.parquet
report.md                # human summary, generated
```

`runs/index.parquet` lists all runs. `mb runs pin <run_id> --as sepa/2026-10_baseline`
marks a milestone. `mb runs diff <a> <b>` shows which config values, data or code changed
between two runs, which answers "why did the number move?" directly.

A pinned run can be re-run; the tool checks the new result matches exactly.

## 7. Research rules

- **Locked final period:** 2024-01-01 onward (to be confirmed). The CLI refuses to
  include it unless `--final`. Each final evaluation is logged with the config hash.
  A config can have at most one final evaluation; after that it is either adopted or dropped.
- **Development folds:** fixed in `configs/baselines.yaml`, e.g. 2010–14, 2014–18, 2018–23.
- **Adoption bar:** a change is adopted only if it beats the current milestone on every
  fold and on the full development period, after costs, and still beats both baselines.
- **Number of variants tried is recorded** per research question, so the final result
  can be judged against how much searching produced it.

## 8. CLI

One entry point, `mb`:

```
mb data fetch <adapter> [--from --to]    # download to raw
mb data build <data-config>              # new dataset version + checks
mb data check <dataset@version>
mb backtest <strategy-config> [--final]
mb baselines <dataset@version>
mb runs list | show | diff | pin
mb paper run <strategy-config>           # daily paper step
mb live run <strategy-config>            # daily live step (later)
```

There is no `scripts/` folder. One-off analysis goes in `notebooks/` and cannot be
imported by production code.

## 9. Repo layout

```
AGENTS.md                 # map, conventions, commands (short)
docs/
  PLAN.md
  decisions/              # one file per decision (why, date, alternatives)
  contracts.md            # canonical bars, research panel, signals, run record
configs/                  # market, data, baselines
strategies/<name>/        # strategy.py + configs/
src/mb/
  sources/                # adapters
  data/                   # raw store, datasets, cleaning, checks
  strategy/               # interfaces + shared indicators
  engine/                 # simulator, sizing, exits, costs
  evaluation/             # metrics, baselines, folds, reports
  runs/                   # run records, registry, diff
  live/                   # scheduler step, paper book, broker adapters
  cli.py
tests/
  fixtures/               # small frozen dataset with known answers
notebooks/
data/  runs/              # git-ignored
```

## 10. Testing

- **Contract tests:** every adapter's output validates against canonical bars.
- **Golden tests:** a small frozen dataset (about 20 stocks, 3 years, including one split,
  one bonus, one delisting) with hand-checked expected trades and metrics. Runs in seconds.
- **Port parity:** while porting, v2 must reproduce v1's clean result on the same inputs
  (6.39% / 23.55% / 258 trades from the adjusted-series scan) before anything changes.
- **Reproducibility test:** re-running a pinned run gives byte-identical metrics.

## 11. What to port from v1

| Keep (port with tests) | v1 location |
|---|---|
| NSE bhavcopy download and parsing | `data_sources/nse_bhavcopy.py`, `storage/bhav_raw_store.py` |
| Corporate-action fetch and parser (merge fix) | `scripts/nse_corporate_actions_fetch.py` |
| Symbol-keyed adjustment matched to observed jumps | `data_sources/sim_prices.py` |
| Security identity | `data_sources/security_identity.py`, `pit.py` |
| SEPA signal logic (trend template, VCP, breakout, RS) | `strategy/`, `indicators/` |
| Portfolio simulator and exits | `lab/engines/portfolio_sim.py`, `backtest/exit_engine.py` |
| Cost model | `lab/engines/portfolio_sim.py` (charges) |
| Paper trade sheet logic | `scripts/sepa_paper_daily.py` |

Left behind: the old signal database, archived optimizers, alternate engines, the
Rust core (re-add only if speed becomes a problem), the Streamlit leftovers, and the
React terminal until the dashboard is designed (§12).

## 12. Build order

Each milestone ends with its exit check passing.

| # | Milestone | Exit check |
|---|---|---|
| M0 | Skeleton: repo, `AGENTS.md`, strict config loader, CLI shell, run records | A dummy strategy run writes a complete run record; unknown config key fails |
| M1 | Data layer: NSE + CA adapters, canonical bars, research panel, checks, dataset versions | Rebuilding from raw twice gives identical hashes; panel matches v1 sim layer |
| M2 | Engine + metrics, ported | Golden tests pass; v1 trade list reproduced on identical signals |
| M3 | Baselines + SEPA port | `sepa/v1_port.yaml` reproduces 6.39% / 23.55% / 258; baselines reported beside it |
| M4 | Research loop: folds, locked period, run diff | A strategy change can be proposed, tested on folds and compared in one report |
| M5 | Momentum strategy + research | Honest comparison of SEPA, momentum and combinations on development folds |
| M6 | Paper trading on VPS | Daily job runs unattended; paper trades match backtest replay |
| M7 | Live with Dhan, safety rails, dashboard | Small real capital; daily reconciliation clean |

M0–M3 is mostly porting proven code. M4 onward is where the strategy question gets answered.

## 13. Decisions needed

1. **Repo name** (working name `multibagger-v2`).
2. **Locked final period start** (proposed 2024-01-01; gives about 2.5 years).
3. **Where it runs:** research on the Mac, daily jobs on the VPS (proposed).
4. **Dashboard:** simple generated HTML report per day first (proposed), app later.
5. **Keep Python + uv + Polars + Pydantic** (proposed; the proven v1 code uses them).
