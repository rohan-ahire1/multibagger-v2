"""The research loop around run records: one final per config, pins, diffs, re-run checks, and the adoption report.

Everything here reads run folders. Nothing is cached; the only file written is `runs/pins.json`, which is the record of
which run each milestone name points at.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from mb.config.loader import ConfigError

PINS_FILE = "pins.json"
HEADLINE = ("cagr_pct", "max_dd_pct", "calmar", "trades")


def manifests(runs_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(m.read_text()) for m in sorted(runs_dir.glob("*/manifest.json"))]


def _run_dir(runs_dir: Path, ref: str) -> Path:
    """`ref` is a run id or a pin name."""
    pins = read_pins(runs_dir)
    run_id = pins.get(ref, ref)
    path = runs_dir / run_id
    if not (path / "manifest.json").exists():
        raise ConfigError(f"no run or pin named '{ref}'")
    return path


def read_pins(runs_dir: Path) -> dict[str, str]:
    f = runs_dir / PINS_FILE
    return json.loads(f.read_text()) if f.exists() else {}


def check_final_unused(runs_dir: Path, config_hash: str) -> None:
    """A config gets one final evaluation; after that it is adopted or dropped."""
    for m in manifests(runs_dir):
        if m["final"] and m["config_hash"] == config_hash:
            raise ConfigError(f"this config already had its final evaluation (run {m['run_id']}); add a new config file")


def pin(runs_dir: Path, run_id: str, name: str) -> None:
    path = _run_dir(runs_dir, run_id)
    m = json.loads((path / "manifest.json").read_text())
    if m["code"]["dirty"] or m["code"]["commit"] is None:
        raise ConfigError(f"run {run_id} was made from uncommitted code; commit, re-run, then pin")
    pins = read_pins(runs_dir)
    if name in pins:
        raise ConfigError(f"pin '{name}' already points at {pins[name]}; pins are not moved, choose a new name")
    pins[name] = m["run_id"]
    (runs_dir / PINS_FILE).write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n")


def _flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(d, dict):
        out: dict[str, Any] = {}
        for k, v in d.items():
            out.update(_flatten(v, f"{prefix}{k}."))
        return out
    return {prefix.rstrip("."): d}


def _headline(metrics: dict[str, Any]) -> dict[str, Any]:
    s = metrics["strategy"]
    return {k: s.get(k) for k in HEADLINE}


def diff(runs_dir: Path, a: str, b: str) -> list[str]:
    """What differs between two runs: config values, data, code, then the headline numbers."""
    da, db = _run_dir(runs_dir, a), _run_dir(runs_dir, b)
    ma, mb_ = json.loads((da / "manifest.json").read_text()), json.loads((db / "manifest.json").read_text())
    lines: list[str] = []
    ca, cb = (_flatten(yaml.safe_load((d / "config.resolved.yaml").read_text())) for d in (da, db))
    for key in sorted(set(ca) | set(cb)):
        if ca.get(key, "<absent>") != cb.get(key, "<absent>"):
            lines.append(f"config  {key}: {ca.get(key, '<absent>')} -> {cb.get(key, '<absent>')}")
    for label, va, vb in (("dataset", ma["dataset"], mb_["dataset"]), ("dataset_hash", ma["dataset_hash"], mb_["dataset_hash"]),
                          ("code.commit", ma["code"]["commit"], mb_["code"]["commit"]),
                          ("code.dirty", ma["code"]["dirty"], mb_["code"]["dirty"]), ("period", ma["period"], mb_["period"])):
        if va != vb:
            lines.append(f"{label}: {va} -> {vb}")
    if not lines:
        lines.append("config, data and code are identical")
    xa, xb = (_headline(json.loads((d / "metrics.json").read_text())) for d in (da, db))
    for k in HEADLINE:
        if xa[k] != xb[k]:
            lines.append(f"result  {k}: {_fmt(xa[k])} -> {_fmt(xb[k])}")
    return lines


def _fmt(v: Any) -> str:
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def verify(runs_dir: Path, ref: str, root: Path) -> list[str]:
    """Re-run a non-final run's config and list every difference from the recorded result (empty = exact match)."""
    from mb.config.loader import load_strategy_config
    from mb.strategy.registry import runner

    path = _run_dir(runs_dir, ref)
    m = json.loads((path / "manifest.json").read_text())
    if m["final"]:
        raise ConfigError("a final run is never re-run; its config has used its one final evaluation")
    cfg = load_strategy_config(Path(m["config_file"]), root)
    if cfg.hash() != m["config_hash"]:
        return [f"config file changed since the run (hash {m['config_hash'][:8]} -> {cfg.hash()[:8]})"]
    result = runner(cfg.strategy.name)(cfg, root)
    problems = []
    recorded = json.loads((path / "metrics.json").read_text())
    if json.loads(json.dumps(result.metrics, sort_keys=True, default=str)) != recorded:
        problems.append("metrics differ from metrics.json")
    if not result.trades.equals(pl.read_parquet(path / "trades.parquet")):
        problems.append("trades differ from trades.parquet")
    return problems


def verdict(candidate: dict[str, Any], pinned: dict[str, Any], metric: str) -> list[dict[str, Any]]:
    """Adoption bar: on the whole period and on every fold, the candidate beats the pinned milestone and both baselines.

    Baselines are read from the candidate's own metrics (same windows). A missing value (for example Calmar with no
    drawdown) counts as failing.
    """
    def num(v: Any) -> float:
        return float(v) if v is not None else float("-inf")

    windows = ["period", *candidate["folds"]]
    rows = []
    for w in windows:
        cand = num((candidate["strategy"] if w == "period" else candidate["folds"][w]).get(metric))
        if w == "period":
            base = num(pinned["strategy"].get(metric))
        else:
            base = num(pinned["folds"].get(w, {}).get(metric))
        tri = num(candidate["baselines"]["nifty500_tri_buy_and_hold"][w].get(metric))
        mom = num(candidate["baselines"]["momentum_12_1"][w].get(metric))
        rows.append({"window": w, "candidate": cand, "pinned": base, "tri": tri, "momentum": mom,
                     "passes": cand > base and cand > tri and cand > mom})
    return rows


def report(runs_dir: Path, question: str, against: str, metric: str) -> tuple[str, bool]:
    """A markdown report for one research question: how many variants were tried, and the adoption verdict for each."""
    runs = [m for m in manifests(runs_dir) if m.get("question") == question]
    if not runs:
        raise ConfigError(f"no runs recorded for question '{question}'")
    pinned_dir = _run_dir(runs_dir, against)
    pinned = json.loads((pinned_dir / "metrics.json").read_text())
    variants = sorted({m["config_hash"] for m in runs})
    lines = [f"# Research question: {question}", "",
             f"- Variants tried: {len(variants)} (distinct configs). Runs: {len(runs)}. Final evaluations: "
             f"{sum(1 for m in runs if m['final'])}.",
             f"- Compared against: `{against}` (run {pinned_dir.name}). Adoption metric: `{metric}`.", ""]
    adopted = False
    latest = {m["config_hash"]: m for m in runs}  # runs are in run-id (time) order: a config's newest run is reported
    for m in latest.values():
        cand = json.loads((runs_dir / m["run_id"] / "metrics.json").read_text())
        rows = verdict(cand, pinned, metric)
        ok = all(r["passes"] for r in rows)
        adopted = adopted or ok
        lines += [f"## {m['strategy']} (config {m['config_hash'][:8]}, run {m['run_id']}) — {'PASSES' if ok else 'fails'} the bar", "",
                  f"| Window | Candidate | Pinned | Nifty 500 TRI | Momentum 12-1 | Passes |", "|---|---|---|---|---|---|"]
        lines += [f"| {r['window']} | {_fmt(r['candidate'])} | {_fmt(r['pinned'])} | {_fmt(r['tri'])} | {_fmt(r['momentum'])} | "
                  f"{'yes' if r['passes'] else 'no'} |" for r in rows]
        lines.append("")
    return "\n".join(lines), adopted
