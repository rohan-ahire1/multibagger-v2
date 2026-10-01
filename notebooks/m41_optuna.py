"""M41 (docs/research/m41.md): walk-forward parameter search with Optuna around the pin m40_deliv40_gold20_b2.

Run: uv run python notebooks/m41_optuna.py <step A|B> <trials>. The study lives in reports/m41/optuna.db, so a later
run with the same step adds trials to it. Then: uv run python notebooks/m41_optuna.py report <step> scores the top
trials and the pin on the step's test fold.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.engine.gate import DataGateError, enforce_data_gate
from mb.engine.rebalance import simulate_targets
from mb.engine.run import JUMPS_FILE, load_sectors
from mb.evaluation.metrics import equity_metrics
from mb.strategy.momentum.params import ParamsM40
from mb.strategy.momentum.targets import targets

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "strategies/momentum/configs/m40_deliv40_gold20_b2.yaml"
OUT = ROOT / "reports/m41"
START, DEV_END = date(2010, 1, 4), date(2023, 12, 31)
STEPS = {"A": {"train_end": date(2013, 12, 31), "test": (date(2014, 1, 1), date(2017, 12, 31))},
         "B": {"train_end": date(2017, 12, 31), "test": (date(2018, 1, 1), date(2023, 12, 31))}}
OFFSETS = (0, 5, 10, 15)
SEED, TOP_K, WORKERS, PARALLEL_TRIALS = 41, 5, 8, 2
PIN = {"lookback": 252, "skip": 21, "top_n": 40, "deliv": 0.4, "gold": 0.2, "ivol": 126, "adv_cr": 2}

_W: dict[str, Any] = {}


def _init() -> None:
    cfg = load_strategy_config(BASE, ROOT)
    path = datasets.dataset_path(ROOT, cfg.strategy.dataset) / datasets.PANEL_FILE
    _W["cfg"] = cfg
    _W["panel"] = (pl.scan_parquet(path).filter(pl.col("date") <= DEV_END)
                   .select("date", "symbol", "security_id", "series", "close", "turnover", "adj_open", "adj_high",
                           "adj_close", "volume", "deliv_qty").collect())
    _W["funds"] = frozenset(pl.scan_parquet(path).filter(pl.col("security_id").str.starts_with("isin:INF"))
                            .select("symbol").unique().collect()["symbol"].to_list())
    _W["sectors"] = load_sectors(ROOT, cfg)
    _W["jumps"] = pl.read_parquet(datasets.dataset_path(ROOT, cfg.strategy.dataset) / JUMPS_FILE)


def params_for(s: dict[str, Any], offset: int) -> ParamsM40:
    d = _W["cfg"].params.model_dump(mode="python")
    d["ranking"].update(lookback_sessions=s["lookback"], skip_sessions=s["skip"])
    d["portfolio"].update(top_n=s["top_n"], hold_rank_max=s["top_n"], inverse_vol_sessions=s["ivol"],
                          fixed_weights={"GOLDBEES": s["gold"]} if s["gold"] > 0 else {})
    d["universe"].update(delivery_drop_frac=s["deliv"] if s["deliv"] > 0 else None, min_adv_inr=s["adv_cr"] * 10_000_000)
    d["schedule"]["decision_offset_sessions"] = offset
    return ParamsM40.model_validate(d)


def equity(s: dict[str, Any], offset: int, end: date) -> pl.DataFrame | None:
    """The book from START to `end` on a panel cut at `end`; None if the data gate refuses it."""
    cfg, p = _W["cfg"], params_for(s, offset)
    panel = _W["panel"].filter(pl.col("date") <= end)
    days = sorted(panel.filter(pl.col("date").is_between(START, end))["date"].unique().to_list())
    bars = panel.select("date", "symbol", pl.col("adj_open").alias("open"), pl.col("adj_close").alias("close"))
    tg = targets(panel, p, START, end, sectors=_W["sectors"], days_per_year=cfg.market.trading_days_per_year,
                 fund_symbols=_W["funds"])
    res = simulate_targets(tg, bars, days, cfg.market, p.initial_capital, None)
    try:
        enforce_data_gate(res.holdings, _W["jumps"])
    except DataGateError:
        return None
    return res.equity


def calmar_on(job: tuple[dict[str, Any], int, date, date, date]) -> dict[str, float] | None:
    s, offset, end, a, b = job
    eq = equity(s, offset, end)
    if eq is None:
        return None
    m = equity_metrics(eq, a, b)
    return {"calmar": m["calmar"], "cagr_pct": m["cagr_pct"], "max_dd_pct": m["max_dd_pct"]}


def four_offsets(pool: ProcessPoolExecutor, s: dict[str, Any], end: date, a: date, b: date) -> dict[str, float] | None:
    rs = list(pool.map(calmar_on, [(s, o, end, a, b) for o in OFFSETS]))
    if any(r is None for r in rs):
        return None
    return {k: float(np.mean([r[k] for r in rs])) for k in rs[0]} | {"calmar_by_offset": [r["calmar"] for r in rs]}


def suggest(t: optuna.Trial) -> dict[str, Any]:
    return {"lookback": t.suggest_int("lookback", 126, 378, step=21), "skip": t.suggest_int("skip", 0, 42, step=7),
            "top_n": t.suggest_int("top_n", 20, 60, step=5), "deliv": t.suggest_float("deliv", 0.0, 0.6, step=0.1),
            "gold": t.suggest_float("gold", 0.0, 0.4, step=0.05), "ivol": t.suggest_int("ivol", 63, 252, step=21),
            "adv_cr": t.suggest_categorical("adv_cr", [1, 2, 3, 5])}


def study(step: str) -> optuna.Study:
    OUT.mkdir(parents=True, exist_ok=True)
    return optuna.create_study(study_name=f"m41_step{step}", storage=f"sqlite:///{OUT / 'optuna.db'}",
                               direction="maximize", sampler=optuna.samplers.TPESampler(seed=SEED), load_if_exists=True)


def search(step: str, n: int) -> None:
    st, end = study(step), STEPS[step]["train_end"]
    if not st.trials:
        st.enqueue_trial(PIN)
    with ProcessPoolExecutor(WORKERS, initializer=_init) as pool:
        def objective(t: optuna.Trial) -> float:
            r = four_offsets(pool, suggest(t), end, START, end)
            if r is None:
                raise optuna.TrialPruned("data gate")
            for k, v in r.items():
                t.set_user_attr(k, v)
            return r["calmar"]
        st.optimize(objective, n_trials=n, n_jobs=PARALLEL_TRIALS)
    done = [t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE]
    print(f"step {step}: {len(done)} complete, {len(st.trials) - len(done)} failed/other; best train Calmar "
          f"{st.best_value:.3f} {st.best_params}")


def _fmt(r: dict[str, Any] | None) -> str:
    return "gate" if r is None else f"{r['calmar']:.3f} ({r['cagr_pct']:.1f}% / {r['max_dd_pct']:.1f}% DD)"


def report(step: str) -> None:
    st, (a, b) = study(step), STEPS[step]["test"]
    done = sorted((t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE), key=lambda t: -t.value)
    pin_trial = next(t for t in st.trials if t.number == 0)
    rows = []
    with ProcessPoolExecutor(WORKERS, initializer=_init) as pool:
        for label, t in [("pin", pin_trial)] + [(f"top{i + 1}", t) for i, t in enumerate(done[:TOP_K])]:
            test = four_offsets(pool, dict(t.params), DEV_END, a, b)
            full = four_offsets(pool, dict(t.params), DEV_END, START, DEV_END)
            rows.append({"label": label, "trial": t.number, "params": t.params, "train_calmar": t.value,
                         "test": test, "full_2010_2023": full})
            print(f"{label:5} #{t.number:<3} train {t.value:.3f}  test {_fmt(test)}  full {_fmt(full)}  {t.params}")
    vals = np.array([t.value for t in done])
    summary = {"step": step, "trials_complete": len(done), "trials_total": len(st.trials),
               "train_calmar_quantiles": {q: float(np.quantile(vals, q)) for q in (0.1, 0.5, 0.9)}, "rows": rows}
    (OUT / f"step{step}_report.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"train Calmar 10/50/90%: {summary['train_calmar_quantiles']}")


if __name__ == "__main__":
    if sys.argv[1] == "report":
        report(sys.argv[2])
    else:
        search(sys.argv[1], int(sys.argv[2]))
