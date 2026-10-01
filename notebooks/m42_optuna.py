"""M42 (docs/research/m42.md): the full walk-forward Optuna search around the pin m40_deliv40_gold20_b2.

Run: uv run python notebooks/m42_optuna.py all [workers]. It runs steps A, B and C (search, then test-fold report),
writes reports/m42/summary.md and step{A,B,C}_report.json, and sends one ntfy alert (topic from $MB_NTFY_TOPIC) when
it finishes or fails. The studies live in reports/m42/optuna.db; a re-run tops each step up to TRIALS and reuses
finished reports, so an interrupted run can simply be started again.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import polars as pl
import requests

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
OUT = ROOT / "reports/m42"
START, DEV_END = date(2010, 1, 4), date(2023, 12, 31)
STEPS = {"A": {"train_end": date(2013, 12, 31), "test": (date(2014, 1, 1), date(2017, 12, 31))},
         "B": {"train_end": date(2017, 12, 31), "test": (date(2018, 1, 1), date(2023, 12, 31))},
         "C": {"train_end": date(2020, 12, 31), "test": (date(2021, 1, 1), date(2023, 12, 31))}}
OFFSETS = (0, 5, 10, 15)
TRIALS, SEED, TOP_K, SLIP_CHECK_BPS, PARALLEL_TRIALS = 300, 42, 5, 25, 2
NTFY_URL = "https://ntfy.sh"
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


def equity(s: dict[str, Any], offset: int, end: date, slip_bps: float | None) -> pl.DataFrame | None:
    """The book from START to `end` on a panel cut at `end`; None if the data gate refuses it."""
    cfg, p = _W["cfg"], params_for(s, offset)
    market = cfg.market if slip_bps is None else cfg.market.model_copy(update={"slippage_bps_per_side": slip_bps})
    panel = _W["panel"].filter(pl.col("date") <= end)
    days = sorted(panel.filter(pl.col("date").is_between(START, end))["date"].unique().to_list())
    bars = panel.select("date", "symbol", pl.col("adj_open").alias("open"), pl.col("adj_close").alias("close"))
    tg = targets(panel, p, START, end, sectors=_W["sectors"], days_per_year=cfg.market.trading_days_per_year,
                 fund_symbols=_W["funds"])
    res = simulate_targets(tg, bars, days, market, p.initial_capital, None)
    try:
        enforce_data_gate(res.holdings, _W["jumps"])
    except DataGateError:
        return None
    return res.equity


def metrics_on(job: tuple[dict[str, Any], int, date, list[tuple[date, date]], float | None]) -> list[dict[str, float]] | None:
    """One run, scored on each (start, end) window."""
    s, offset, end, windows, slip = job
    eq = equity(s, offset, end, slip)
    if eq is None:
        return None
    out = []
    for a, b in windows:
        m = equity_metrics(eq, a, b)
        out.append({"calmar": m["calmar"], "cagr_pct": m["cagr_pct"], "max_dd_pct": m["max_dd_pct"]})
    return out


def four_offsets(pool: ProcessPoolExecutor, s: dict[str, Any], end: date, windows: list[tuple[date, date]],
                 slip: float | None = None) -> list[dict[str, Any] | None]:
    """Per window: the mean over OFFSETS of Calmar, CAGR and max DD, plus Calmar by offset; None if any is gated."""
    rs = list(pool.map(metrics_on, [(s, o, end, windows, slip) for o in OFFSETS]))
    if any(r is None for r in rs):
        return [None] * len(windows)
    return [{k: float(np.mean([r[i][k] for r in rs])) for k in rs[0][i]} | {"calmar_by_offset": [r[i]["calmar"] for r in rs]}
            for i in range(len(windows))]


def suggest(t: optuna.Trial) -> dict[str, Any]:
    lookback = t.suggest_int("lookback", 126, 378, step=21)
    # A name is eligible once it has `lookback` sessions, so a longer volatility window has no data for new listings.
    return {"lookback": lookback, "skip": t.suggest_int("skip", 0, 42, step=7),
            "top_n": t.suggest_int("top_n", 20, 60, step=5), "deliv": t.suggest_float("deliv", 0.0, 0.8, step=0.1),
            "gold": t.suggest_float("gold", 0.0, 0.6, step=0.05),
            "ivol": t.suggest_int("ivol", 63, min(252, lookback), step=21),
            "adv_cr": t.suggest_categorical("adv_cr", [1, 2, 3, 5])}


def study(step: str) -> optuna.Study:
    OUT.mkdir(parents=True, exist_ok=True)
    return optuna.create_study(study_name=f"m42_step{step}", storage=f"sqlite:///{OUT / 'optuna.db'}",
                               direction="maximize", sampler=optuna.samplers.TPESampler(seed=SEED), load_if_exists=True)


def log(msg: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with (OUT / "progress.log").open("a") as f:
        f.write(line + "\n")


def search(pool: ProcessPoolExecutor, step: str) -> None:
    st, end = study(step), STEPS[step]["train_end"]
    if not st.trials:
        st.enqueue_trial(PIN)
    # Trials left RUNNING by an interrupted run are not counted; they stay in the db as they were.
    n = TRIALS - sum(t.state != optuna.trial.TrialState.RUNNING for t in st.trials)

    def objective(t: optuna.Trial) -> float:
        r = four_offsets(pool, suggest(t), end, [(START, end)])[0]
        if r is None:
            raise optuna.TrialPruned("data gate")
        for k, v in r.items():
            t.set_user_attr(k, v)
        return r["calmar"]

    def progress(st: optuna.Study, t: optuna.trial.FrozenTrial) -> None:
        if t.number % 10 == 0:
            log(f"step {step}: trial {t.number}, best train Calmar {st.best_value:.3f}")

    log(f"step {step}: search, {max(n, 0)} trials to run")
    if n > 0:
        st.optimize(objective, n_trials=n, callbacks=[progress], n_jobs=PARALLEL_TRIALS)
    log(f"step {step}: search done, best train Calmar {st.best_value:.3f} {st.best_params}")


def report(pool: ProcessPoolExecutor, step: str) -> dict[str, Any]:
    path = OUT / f"step{step}_report.json"
    st, test = study(step), STEPS[step]["test"]
    done = [t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if path.exists() and json.loads(path.read_text())["trials_complete"] == len(done):
        return json.loads(path.read_text())
    done.sort(key=lambda t: -t.value)
    pin_trial = next(t for t in st.trials if t.number == 0)
    rows = []
    windows = [test, (START, DEV_END)]
    for label, t in [("pin", pin_trial)] + [(f"top{i + 1}", t) for i, t in enumerate(done[:TOP_K])]:
        base = four_offsets(pool, dict(t.params), DEV_END, windows)
        slip = four_offsets(pool, dict(t.params), DEV_END, windows, SLIP_CHECK_BPS)
        rows.append({"label": label, "trial": t.number, "params": t.params, "train_calmar": t.value,
                     "test": base[0], "full_2010_2023": base[1], "test_slip25": slip[0], "full_slip25": slip[1]})
        log(f"step {step}: {label} #{t.number} train {t.value:.3f} test {_fmt(base[0])} test@25bps {_fmt(slip[0])}")
    vals = np.array([t.value for t in done])
    out = {"step": step, "train_end": str(STEPS[step]["train_end"]), "test": [str(d) for d in test],
           "trials_complete": len(done), "trials_total": len(st.trials),
           "train_calmar_quantiles": {str(q): float(np.quantile(vals, q)) for q in (0.1, 0.5, 0.9)}, "rows": rows}
    path.write_text(json.dumps(out, indent=2, default=str))
    return out


def _fmt(r: dict[str, Any] | None) -> str:
    return "gate" if r is None else f"{r['calmar']:.3f} ({r['cagr_pct']:.1f}% / {r['max_dd_pct']:.1f}% DD)"


def _cal(r: dict[str, Any] | None) -> float:
    return float("nan") if r is None else r["calmar"]


def summary(reports: list[dict[str, Any]], started: float) -> str:
    lines = [f"# M42 summary ({datetime.now().isoformat(timespec='minutes')}, {(time.time() - started) / 3600:.1f} h)", "",
             "Four-offset means. Pin = momentum/m40_deliv40_gold20_b2. Rules: docs/research/m42.md.", ""]
    checks = []
    for r in reports:
        pin, sel = r["rows"][0], r["rows"][1]
        lines += [f"## Step {r['step']}: train 2010-01-04..{r['train_end']}, test {r['test'][0]}..{r['test'][1]}", "",
                  f"Trials complete {r['trials_complete']}/{r['trials_total']}; train Calmar 10/50/90%: "
                  + " / ".join(f"{v:.3f}" for v in r["train_calmar_quantiles"].values()), "",
                  "| Setting | Trial | Train | Test | Test @25bps | 2010–23 | 2010–23 @25bps | Params |",
                  "|---|---|---|---|---|---|---|---|"]
        for row in r["rows"]:
            lines.append(f"| {row['label']} | {row['trial']} | {row['train_calmar']:.3f} | {_fmt(row['test'])} | "
                         f"{_cal(row['test_slip25']):.3f} | {_cal(row['full_2010_2023']):.3f} | "
                         f"{_cal(row['full_slip25']):.3f} | {row['params']} |")
        lines.append("")
        checks.append((r["step"], _cal(sel["test"]) > _cal(pin["test"]), _cal(sel["test_slip25"]) > _cal(pin["test_slip25"]),
                       sel["params"]))
    lines += ["## Pre-registered bar", ""]
    for step, beat, beat25, p in checks:
        lines.append(f"- Step {step}: selected beats pin on test: {'yes' if beat else 'NO'}; at 25 bps: "
                     f"{'yes' if beat25 else 'NO'}; selected {p}")
    lines += [f"- Pin: {PIN}", "- Direction agreement across steps: judged by hand from the selected settings above.", ""]
    passed = all(b and b25 for _, b, b25, _ in checks)
    lines.append(f"**Test-fold bars: {'all pass' if passed else 'not all pass'}.**")
    return "\n".join(lines) + "\n"


def notify(msg: str) -> None:
    topic = os.environ.get("MB_NTFY_TOPIC")
    log(f"alert: {msg}")
    if topic:
        requests.post(f"{NTFY_URL}/{topic}", data=msg.encode(), headers={"Title": "M42 Optuna run"}, timeout=15)


def main(workers: int) -> None:
    started = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    log(f"M42 start, {workers} workers")
    try:
        reports = []
        with ProcessPoolExecutor(workers, initializer=_init) as pool:
            for step in STEPS:
                search(pool, step)
                reports.append(report(pool, step))
        (OUT / "summary.md").write_text(summary(reports, started))
        verdict = [f"{r['step']}: sel {_cal(r['rows'][1]['test']):.2f} vs pin {_cal(r['rows'][0]['test']):.2f}" for r in reports]
        notify(f"M42 done in {(time.time() - started) / 3600:.1f} h. Test Calmar " + "; ".join(verdict)
               + f". Summary: {OUT / 'summary.md'}")
    except Exception:
        log(traceback.format_exc())
        notify(f"M42 FAILED after {(time.time() - started) / 3600:.1f} h; see {OUT / 'progress.log'}")
        raise


if __name__ == "__main__":
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    if sys.argv[1] == "all":
        main(int(sys.argv[2]) if len(sys.argv) > 2 else 4)
