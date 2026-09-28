"""M4: lock reach, one final per config, pins, run diff, re-run check, and the adoption bar."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from mb.cli import app
from mb.config.loader import ConfigError, enforce_lock, load_baselines, load_strategy_config
from mb.config.models import BaselinesConfig
from mb.runs import research

ROOT = Path(__file__).resolve().parents[1]


def _run(runs: Path, run_id: str, *, cfg_hash="aaaaaaaa1", final=False, dirty=False, question=None, values=None, commit="c1",
         metrics=None) -> None:
    d = runs / run_id
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({
        "run_id": run_id, "strategy": "sepa/x", "config_hash": cfg_hash, "config_file": "x.yaml", "dataset": "d@1",
        "dataset_hash": "h", "code": {"commit": commit, "dirty": dirty}, "period": ["2010-01-04", "2023-12-31"],
        "final": final, "question": question, "started_at": "t"}))
    (d / "config.resolved.yaml").write_text(yaml.safe_dump(values or {"strategy": {"params": {"a": 1, "b": {"c": 2}}}}))
    (d / "metrics.json").write_text(json.dumps(metrics or _metrics(1.0)))


def _metrics(calmar: float, fold_calmar: float | None = None, tri: float = 0.3, mom: float = 0.4) -> dict:
    f = calmar if fold_calmar is None else fold_calmar
    base = lambda v: {"period": {"calmar": v}, "f1": {"calmar": v}}  # noqa: E731
    return {"strategy": {"cagr_pct": 10.0, "max_dd_pct": 20.0, "calmar": calmar, "trades": 100},
            "folds": {"f1": {"calmar": f}},
            "baselines": {"nifty500_tri_buy_and_hold": base(tri), "momentum_12_1": base(mom)}}


def test_lock_counts_the_settle_window(tmp_path):
    cfg = load_strategy_config(ROOT / "strategies/sepa/configs/v1_port_dev.yaml", ROOT)
    enforce_lock(cfg, final=False)  # ends 2023-12-31 with no settle window
    engine = cfg.params.engine.model_copy(update={"settle_calendar_days": 220})
    reaching = type(cfg)(cfg.strategy, cfg.params.model_copy(update={"engine": engine}), cfg.market, cfg.baselines, cfg.strategy_path)
    with pytest.raises(ConfigError, match="locked"):
        enforce_lock(reaching, final=False)


def test_folds_must_stay_out_of_the_locked_period():
    data = yaml.safe_load((ROOT / "configs/baselines.yaml").read_text())
    data["folds"][-1]["end"] = date(2024, 6, 30)
    with pytest.raises(ValueError, match="locked"):
        BaselinesConfig.model_validate(data)


def test_real_folds_load():
    b = load_baselines(ROOT)
    assert [f.name for f in b.folds] == ["f1_2010_2013", "f2_2014_2017", "f3_2018_2023"]


def test_one_final_per_config(tmp_path):
    _run(tmp_path, "r1", cfg_hash="h1", final=True)
    _run(tmp_path, "r2", cfg_hash="h2", final=False)
    with pytest.raises(ConfigError, match="already had its final"):
        research.check_final_unused(tmp_path, "h1")
    research.check_final_unused(tmp_path, "h2")


def test_pin_needs_clean_code_and_never_moves(tmp_path):
    _run(tmp_path, "clean")
    _run(tmp_path, "dirty", dirty=True)
    with pytest.raises(ConfigError, match="uncommitted"):
        research.pin(tmp_path, "dirty", "m1")
    research.pin(tmp_path, "clean", "m1")
    assert research.read_pins(tmp_path) == {"m1": "clean"}
    with pytest.raises(ConfigError, match="already points"):
        research.pin(tmp_path, "clean", "m1")


def test_diff_names_the_changed_value_and_code(tmp_path):
    _run(tmp_path, "a")
    _run(tmp_path, "b", commit="c2", values={"strategy": {"params": {"a": 1, "b": {"c": 3}}}}, metrics=_metrics(2.0))
    lines = research.diff(tmp_path, "a", "b")
    assert "config  strategy.params.b.c: 2 -> 3" in lines
    assert "code.commit: c1 -> c2" in lines
    assert any(line.startswith("result  calmar: 1.00 -> 2.00") for line in lines)
    assert research.diff(tmp_path, "a", "a")[0] == "config, data and code are identical"


def test_adoption_needs_every_window_and_both_baselines():
    pinned = _metrics(1.0)
    assert all(r["passes"] for r in research.verdict(_metrics(1.5), pinned, "calmar"))
    worse_fold = research.verdict(_metrics(1.5, fold_calmar=0.9), pinned, "calmar")
    assert [r["passes"] for r in worse_fold] == [True, False]
    below_momentum = research.verdict(_metrics(1.5, mom=2.0), pinned, "calmar")
    assert not any(r["passes"] for r in below_momentum)
    missing = _metrics(1.5)
    missing["strategy"]["calmar"] = None
    assert not research.verdict(missing, pinned, "calmar")[0]["passes"]


def test_report_counts_variants(tmp_path):
    _run(tmp_path, "base")
    _run(tmp_path, "v1", cfg_hash="h1", question="q", metrics=_metrics(1.5))
    _run(tmp_path, "v1b", cfg_hash="h1", question="q", metrics=_metrics(1.5))
    _run(tmp_path, "v2", cfg_hash="h2", question="q", metrics=_metrics(0.5))
    text, adopted = research.report(tmp_path, "q", "base", "calmar")
    assert "Variants tried: 2" in text and "Runs: 3" in text and adopted
    with pytest.raises(ConfigError):
        research.report(tmp_path, "nope", "base", "calmar")


def test_cli_diff_and_pin_errors_are_clean(tmp_path):
    (tmp_path / "runs").mkdir()
    res = CliRunner().invoke(app, ["runs", "diff", "x", "y", "--root", str(tmp_path)])
    assert res.exit_code == 2 and "error:" in res.output
