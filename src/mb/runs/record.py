"""Run records: everything needed to trace and reproduce a number."""
from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from mb.config.loader import Resolved

RECORD_FILES = ("config.resolved.yaml", "manifest.json", "metrics.json", "trades.parquet", "equity.parquet", "report.md")


@dataclass(frozen=True)
class RunResult:
    metrics: dict[str, Any]
    trades: pl.DataFrame
    equity: pl.DataFrame


def git_state(root: Path) -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        return out.stdout.strip()

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return {"commit": commit, "dirty": bool(status) if status is not None else None}


def _dataset_hash(root: Path, ref: str) -> str | None:
    """The dataset panel's sha256 from its manifest, or None if the dataset is not on this machine."""
    from mb.data import datasets

    try:
        return datasets.read_manifest(datasets.dataset_path(root, ref))["outputs"][datasets.PANEL_FILE]["sha256"]
    except FileNotFoundError:
        return None


def _report(cfg: Resolved, run_id: str, result: RunResult) -> str:
    s = cfg.strategy
    return (
        f"# Run {run_id}\n\n"
        f"- Strategy: `{s.name}/{s.version}`\n- Dataset: `{s.dataset}`\n"
        f"- Period: {s.period.start} → {s.period.end}\n"
        f"- Config hash: `{cfg.hash()}`\n\n"
        f"## Metrics\n\n```json\n{json.dumps(result.metrics, indent=2, sort_keys=True)}\n```\n"
    )


def write_run(cfg: Resolved, result: RunResult, root: Path, runs_dir: Path, final: bool,
              started: datetime, finished: datetime, question: str | None = None) -> Path:
    run_id = f"{started.strftime('%Y%m%d-%H%M%S')}-{cfg.hash()[:8]}"
    out = runs_dir / run_id
    out.mkdir(parents=True, exist_ok=False)
    (out / "config.resolved.yaml").write_text(cfg.yaml_text())
    manifest = {
        "run_id": run_id,
        "strategy": f"{cfg.strategy.name}/{cfg.strategy.version}",
        "config_hash": cfg.hash(),
        "config_file": str(cfg.strategy_path),
        "dataset": cfg.strategy.dataset,
        "dataset_hash": _dataset_hash(root, cfg.strategy.dataset),
        "code": git_state(root),
        "period": [cfg.strategy.period.start.isoformat(), cfg.strategy.period.end.isoformat()],
        "final": final,
        "question": question,
        "host": platform.node(),
        "started_at": started.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 3),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (out / "metrics.json").write_text(json.dumps(result.metrics, indent=2, sort_keys=True) + "\n")
    result.trades.write_parquet(out / "trades.parquet")
    result.equity.write_parquet(out / "equity.parquet")
    (out / "report.md").write_text(_report(cfg, run_id, result))
    return out


def list_runs(runs_dir: Path) -> pl.DataFrame:
    """The index is rebuilt from run folders each time; never appended to."""
    rows = []
    for m in sorted(runs_dir.glob("*/manifest.json")):
        d = json.loads(m.read_text())
        rows.append({"run_id": d["run_id"], "strategy": d["strategy"], "config_hash": d["config_hash"][:8],
                     "dataset": d["dataset"], "final": d["final"], "started_at": d["started_at"]})
    return pl.DataFrame(rows, schema={"run_id": pl.String, "strategy": pl.String, "config_hash": pl.String,
                                      "dataset": pl.String, "final": pl.Boolean, "started_at": pl.String})


def now() -> datetime:
    return datetime.now(UTC)
