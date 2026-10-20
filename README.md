# Multibagger v2

A reproducible research, backtesting and paper-trading system for NSE (India) cash equities.

**Live research dashboard: [multibagger.rohanahire.com](https://multibagger.rohanahire.com)**

> Research and paper trading only. No real orders are placed, and nothing here is financial advice.

## What it does

Multibagger v2 turns raw NSE exchange files into clean, versioned datasets, backtests strategy configs against them
under strict research rules, and runs the strategies that pass as paper-trading books every trading day on a VPS.
Every number it reports can be traced to the exact data version, code commit and config that produced it.

It is a rebuild of [Multibagger v1](https://github.com/rohan-ahire1/Multibagger). v1 had several backtest engines,
settings that differed between code and config, and a signal store that kept appending old scans, which inflated its
results. v2 was designed so those mistakes cannot happen again, and its engine reproduces v1's corrected reference
run trade for trade (`tests/test_m2_engine.py`).

## Key features

- **Data layer from raw exchange files.** Downloads NSE bhavcopy archives, delivery data and corporate actions into an
  immutable raw store, then builds versioned datasets (`nse_research@<label>`) with split, bonus and demerger
  adjustment matched to observed price jumps, ISIN-based symbol-rename handling, and checks that run on every build.
- **Data gate.** A backtest is refused if any trade was held through a price jump that no corporate action explains.
- **One engine, two simulators.** A signal-driven simulator (breakout strategies) and a target-weight rebalancer
  (momentum and blends), both with slippage and statutory charges.
- **Strategies.** Month-end momentum (ranking, volatility-adjusted scores, hold buffers, sector caps, a gold sleeve
  and a market-regime switch), SEPA/VCP breakouts (a port of v1), fixed-weight blends of other configs, and an
  options-signal stock book. 1,300+ strategy configs live in `strategies/*/configs/`.
- **Research rules enforced in code.** Configs are strict (no defaults, unknown keys fail). Each run writes a record
  (resolved config, manifest, metrics, trades, equity). A locked final test period needs `--final`, and each config
  gets one final run. A candidate is adopted only if it beats the pinned strategy and two baselines (Nifty 500 TRI
  buy-and-hold and 12-1 momentum) on the whole period and on every development fold.
- **Pre-registered research.** 113 research write-ups in `docs/research/`, each stating the question and the check
  before the runs, then recording the results, including the ideas that failed.
- **Paper trading.** `mb paper daily` advances each book one session at a time: corporate actions on held names, whole-share
  fills at the open, marks at the close, and month-end orders. It then replays the backtest over the same dates and checks
  that the picks match exactly. Alerts go out through ntfy. systemd user timers in `deploy/` run three books after
  the NSE close.
- **Indian tax model** (`src/mb/evaluation/tax.py`): FIFO lots, short- and long-term buckets, and loss carry-forward.
- **Tests.** About 290 pytest tests, including engine parity with v1, data adjustment and paper/backtest agreement.

## Tech stack

Python 3.12 · Polars · PyArrow/Parquet · NumPy · Pydantic · Typer · uv · pytest · Optuna (dev) · systemd timers ·
ntfy alerts

## Architecture

```
sources ──► raw store ──► canonical bars ──► research dataset ──► strategy ──► engine ──► evaluation
 (NSE)      (immutable    (one standard      (adjusted + raw     (signals or   (fills,     (metrics,
            downloads)     format)            columns, checks)    target        equity,     baselines,
                                                                  weights)      trades)     run record)
                                                                                    │
                                                                     paper book ◄───┘  (same targets, same engine)
```

| Path | What |
|---|---|
| `src/mb/sources/` | NSE bhavcopy, delivery and corporate-action adapters |
| `src/mb/data/` | Corporate actions, adjustment, renames, checks, dataset builds |
| `src/mb/engine/` | Signal simulator, target-weight rebalancer, data gate |
| `src/mb/strategy/` | Momentum, SEPA, VCP, blend and options-book strategies plus the registry |
| `src/mb/evaluation/` | Metrics, baselines, tax |
| `src/mb/runs/` | Run records, pins, diffs, re-run checks, adoption reports |
| `src/mb/live/` | Paper book, NSE calendar, replay check, alerts, daily job |
| `configs/` | Market costs, data rules, baselines, paper books, tax |
| `docs/` | `PLAN.md` (design), `paper.md` (paper trading), `research/` (milestones) |

Design notes: [docs/PLAN.md](docs/PLAN.md). Developer guide: [AGENTS.md](AGENTS.md).

## Run locally

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). Market data is not in the repo (`data/` and `runs/` are
git-ignored), so the first step is downloading it from NSE.

```bash
uv sync
uv run pytest

# download raw NSE data, then build an immutable dataset
uv run mb data fetch bhavcopy configs/data/nse_research.yaml --from 2024-01-01 --to 2024-12-31
uv run mb data fetch corporate-actions configs/data/nse_research.yaml --start-year 2024 --end-year 2024
uv run mb data build configs/data/nse_research.yaml --version mylabel

# backtest a strategy config and inspect the run
uv run mb backtest strategies/momentum/configs/<config>.yaml
uv run mb runs list
uv run mb runs diff <run_a> <run_b>

# paper trading (what the VPS timer runs)
uv run mb paper daily configs/paper/<book>.yaml
uv run mb paper status configs/paper/<book>.yaml
```

Strategy configs name the dataset version they read, so point a config at the label you built. Alerts are optional:
set `MB_NTFY_TOPIC` to an [ntfy](https://ntfy.sh) topic to receive them; without it messages are only printed.
