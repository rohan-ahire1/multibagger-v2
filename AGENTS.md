# Multibagger v2

NSE cash-equity research and trading system. Read `docs/HANDOFF.md` (context, traps, v1 data
locations) then `docs/PLAN.md` (design, milestones) before changing anything.

**Status:** M0 done (skeleton). Next: M1 (data layer). Build order is `docs/PLAN.md` §12.

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
| `configs/market/` | Costs, slippage, idle-cash yield (one file per market) |
| `configs/baselines.yaml` | Locked period start (folds and benchmarks come in M3/M4) |
| `strategies/<name>/configs/` | Strategy configs (one file per version) |
| `src/mb/config/` | Strict Pydantic models (`models.py`) and loader (`loader.py`) |
| `src/mb/strategy/` | `registry.py` maps strategy name → params model + runner |
| `src/mb/runs/record.py` | Run record writer and index |
| `src/mb/{sources,data,engine,evaluation,live}/` | Empty until their milestones |
| `docs/reference/` | v1 reference trades, metrics, resolved settings |
| `tests/` | `uv run pytest` |

## Commands

```
uv run mb backtest <strategy-config> [--final]   # writes runs/<run_id>/
uv run mb runs list
uv run pytest
```

Run record: `config.resolved.yaml`, `manifest.json` (code commit, config hash, dataset), `metrics.json`,
`trades.parquet`, `equity.parquet`, `report.md`.

## Adding a strategy

Create `strategies/<name>/`, define a strict `Params` model and a `run(cfg) -> RunResult`, register both in
`src/mb/strategy/registry.py`.
