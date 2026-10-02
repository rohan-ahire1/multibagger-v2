# Multibagger v2

NSE cash-equity research and trading system. Read `docs/HANDOFF.md` (context, traps, v1 data
locations) then `docs/PLAN.md` (design, milestones) before changing anything.

**Status:** M0 (skeleton), M1 (data layer), M2 (engine + metrics), M3 (baselines + SEPA port), M4 (research loop) and M5 (momentum + blends, `docs/research/m5.md`) done. M6 (paper trading on the VPS, `docs/paper.md`) running from the 2026-09-30 close; M8 added a second book (40 names, `docs/research/m8.md`). Both books are stocks only (`docs/paper.md`). Next: M7 (live with Dhan). Build order is `docs/PLAN.md` §12.

## Rules

1. No values in code. Every parameter lives in a YAML config. No defaults in config models; unknown keys fail.
2. No `scripts/` folder. Everything runs through the `mb` CLI. One-off analysis goes in `notebooks/` and is never imported.
3. Raw data is immutable. Derived data is rebuilt from raw, never appended to.
4. Every reported number comes with its run id and config file. Runs are in `runs/<run_id>/`.
5. Ratios and indicators use `adj_*` columns; absolute levels (min price, min ₹ turnover) use raw columns.
6. The locked test period (`configs/baselines.yaml: locked_from`) needs `--final`. A config gets one final evaluation.
7. A config used for a pinned result is never edited. Add a new file.
8. Port from v1 only what `docs/HANDOFF.md` §6 lists, with tests. v1 is reference only (`~/projects/Multibagger`); its data folders are read-only.
9. Do not quote v1's 12–21% numbers. The trusted baseline is 6.39% CAGR / 23.55% max DD / 258 trades.
10. No AI attribution in commit messages. Branch before committing; do not push without asking.

## Layout

| Path | What |
|---|---|
| `configs/market/` | Costs, slippage, idle-cash yield, sector map path (one file per market) |
| `configs/data/` | Data config (`nse_research.yaml`: sources, adjustment rules, check limits), CA overrides CSV, `verified_price_moves.csv` (reviewed real jumps the gate allows) |
| `configs/baselines.yaml` | Locked period start, development folds, adoption metric, Nifty 500 TRI file, 12-1 momentum baseline settings |
| `strategies/<name>/configs/` | Strategy configs (one file per version) |
| `src/mb/config/` | Strict Pydantic models (`models.py`) and loader (`loader.py`) |
| `src/mb/strategy/` | `registry.py` maps strategy name → params model + runner |
| `src/mb/runs/record.py` | Run record writer and index |
| `src/mb/runs/research.py` | One-final-per-config check, pins, run diff, re-run check, adoption report |
| `src/mb/sources/` | Adapters: `nse_bhavcopy.py` (download + parse to canonical bars), `nse_corporate_actions.py` |
| `src/mb/data/` | `corporate_actions.py` (feed + overrides), `adjust.py` (jump-matched adjustment), `checks.py`, `build.py`, `datasets.py` |
| `src/mb/engine/` | `config.py` (engine rules), `simulate.py` (signal-driven simulator), `rebalance.py` (target-weight simulator for momentum and the 12-1 baseline), `gate.py` (unexplained-jump refusal), `run.py` (bars + sectors + simulate, then `score`: gate + metrics + baselines) |
| `src/mb/evaluation/` | `metrics.py`: equity, exposure and trade metrics. `baselines.py`: Nifty 500 TRI buy-and-hold and 12-1 momentum, added to every run's `metrics.baselines` |
| `src/mb/strategy/sepa/` | SEPA/VCP: `signals.py` (features, RS rank, breakout rule), `contraction.py`, `params.py`, `run.py` |
| `src/mb/strategy/vcp/` | M9 Minervini VCP (`docs/research/m8_vcp.md`): `features.py` (trend template, RS rank), `pattern.py` (swings, base, dry-up, breakout), `check.py` (funnel + chart page), `run.py` |
| `src/mb/strategy/momentum/` | Month-end momentum: `targets.py` (ranking, stocks-only filter, vol-adjusted score, hold buffer, regime), `params.py`, `run.py` |
| `src/mb/strategy/blend/` | Fixed-weight mix of existing strategy configs, each pinned by config hash |
| `docs/research/` | Pre-registration and results per research milestone |
| `src/mb/live/` | M6 paper trading: `calendar.py` (NSE holiday list, month-end), `paper.py` (book: fills, corporate actions, jump refusal), `replay.py` (backtest check), `alerts.py` (ntfy), `daily.py` (the daily job) |
| `configs/paper/` | Paper configs; each pins its strategy config by resolved hash |
| `deploy/` | systemd user service + timer for the daily job on the VPS |
| `configs/reference/` | Symbol → industry map for the sector caps |
| `docs/reference/` | v1 reference trades, metrics, resolved settings |
| `configs/dashboard/` | Dashboard bundle config: which runs, groups, paper books, UI sizes |
| `src/mb/dashboard/` | Bundle exporter (run records + dataset prices + paper books to one JSON) |
| `web/` | Research dashboard app (React + Vite); see `web/README.md` |
| `tests/` | `uv run pytest` |

## Commands

```
uv run mb backtest <strategy-config> [--final]   # writes runs/<run_id>/
uv run mb runs list
uv run mb runs diff <run|pin> <run|pin>        # what changed in config, data, code, and headline numbers
uv run mb runs pin <run> --as <strategy>/<name> # milestone; refuses dirty-code runs, never moves a pin
uv run mb runs verify <run|pin>                # re-run a non-final run; must match the record exactly
uv run mb backtest <cfg> --question <id>       # tag a run to a research question (variants are counted per question)
uv run mb research report <id> --against <pin> # variants tried + adoption verdict per fold -> reports/<id>.md
uv run mb data build configs/data/nse_research.yaml --version <label>   # new immutable dataset, runs checks
uv run mb data check nse_research@<label>                              # recorded checks + file hashes
uv run mb data fetch bhavcopy configs/data/nse_research.yaml --from D --to D
uv run mb data fetch corporate-actions configs/data/nse_research.yaml --start-year Y --end-year Y
uv run mb paper daily configs/paper/momentum_voladj_stocks.yaml [--no-fetch] [--today D]   # the VPS daily job
uv run mb paper status configs/paper/momentum_voladj_stocks.yaml
uv run mb dashboard export configs/dashboard/research.yaml [--data-root D]   # writes web/public/bundle.json; then `npm run dev` in web/
uv run mb vcp check <vcp-config> [--sample 30 --seed 1]  # VCP funnel + breakout charts (no returns) -> reports/vcp-check/
uv run pytest
```

Run record: `config.resolved.yaml`, `manifest.json` (code commit, config hash, dataset), `metrics.json`,
`trades.parquet`, `equity.parquet`, `report.md`.

## Adding a strategy

Create `strategies/<name>/`, define a strict `Params` model and a `run(cfg, root) -> RunResult`, register both in
`src/mb/strategy/registry.py`.

## Raw data on this Mac

`data/` is git-ignored. `data/raw/nse_bhavcopy/<year>/<date>.zip` are symlinks to v1's
`~/projects/Multibagger/data/nse_bhavcopy_raw/` (nothing copied; disk is tight). New downloads land beside them as real
files. `data/raw/nse_corporate_actions/` and `data/raw/benchmarks/` are copies of v1's reference files.
Datasets go in `data/datasets/<name>/<version>/` (`panel.parquet` = canonical bars + `adj_*` columns).
Current dataset: `nse_research@2026-09-29b` (data through 2026-07-17): corporate actions re-keyed by ISIN, three manual
overrides, one verified move (see `docs/research/m5.md`). `nse_research@2026-09-29` equals v1's sim layer exactly and backs
the M3/M4 pins.

## v1 behaviours kept on purpose (parity)

- Slippage and charges are multiplied in v1's order (`price * slip * charge`, separate factors). A pre-combined factor
  changes float rounding, and a cash-limited fill (`cost <= cash`) can then flip by 1 ulp and move a fill by a day.
- Engine parity check: `tests/test_m2_engine.py::test_v1_reference_trades_reproduced_on_identical_signals` runs v1's 294
  signals (`docs/reference/v1_reference_signals.csv`) and matches all 258 trades of `docs/reference/v1_reference_trades.csv`.
- `settle_calendar_days` (v1 used 220) reads bars past `period.end`. For a dev config this can reach the locked period, so
  dev configs use 0 (open positions are then closed at the last bar with status `open`).
- SEPA port (`strategies/sepa/configs/v1_port.yaml`): v1 never applied its series filter in the scan, so BE-series rows were in
  the universe and RS pool. The config keeps `allowed_series: [EQ, BE]` for parity; new configs use `[EQ]`.
- SEPA signal parity: all 294 v1 signals are reproduced. Nine 2010 signals differ from v1's `entry_ref`/`stop` by ~1e-15.
  That flips one cash-limited fill in 2017, so the unpatched run gives 257 trades / 6.72% CAGR. With v1's exact values for
  those two columns it gives 258 / 6.39% / 23.55% / 0.27 (`tests/test_m3_sepa.py`).
- `v1_port.yaml` has had its one `--final` run (run 20260928-201856-74c7b90c). Use `v1_port_dev.yaml` (ends 2023-12-31) for dev.
- Research rules in code: the lock counts `period.end + settle_calendar_days`; a config hash gets one `--final` run; a
  candidate is adopted only if it beats the pinned run and both baselines on `adoption.metric` on the whole period and every fold.
