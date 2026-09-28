"""M0 exit check: a dummy run writes a complete record; bad configs fail clearly."""
import json
from datetime import date
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from mb.cli import app
from mb.config.loader import ConfigError, enforce_lock, load_strategy_config
from mb.runs.record import RECORD_FILES

REPO = Path(__file__).resolve().parents[1]
SMOKE = REPO / "strategies/dummy/configs/smoke.yaml"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    shutil.copytree(REPO / "configs", tmp_path / "configs")
    return tmp_path


def write_cfg(root: Path, **overrides) -> Path:
    data = yaml.safe_load(SMOKE.read_text())
    data.update(overrides)
    p = root / "cfg.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_dummy_run_writes_complete_record(root: Path):
    res = CliRunner().invoke(app, ["backtest", str(SMOKE), "--root", str(root)])
    assert res.exit_code == 0, res.output
    (run_dir,) = (root / "runs").iterdir()
    assert sorted(p.name for p in run_dir.iterdir()) == sorted(RECORD_FILES)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert len(manifest["config_hash"]) == 64 and manifest["dataset"] == "nse_research@2026-09-28"
    assert {"commit", "dirty"} <= manifest["code"].keys()


def test_same_config_same_hash():
    a = load_strategy_config(SMOKE, REPO)
    b = load_strategy_config(SMOKE, REPO)
    assert a.hash() == b.hash()


def test_unknown_top_level_key_fails(root: Path):
    with pytest.raises(ConfigError, match="extra_key"):
        load_strategy_config(write_cfg(root, extra_key=1), root)


def test_missing_key_fails(root: Path):
    data = yaml.safe_load(SMOKE.read_text())
    del data["market"]
    p = root / "cfg.yaml"
    p.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError, match="market"):
        load_strategy_config(p, root)


def test_unknown_param_fails(root: Path):
    with pytest.raises(ConfigError, match="bogus"):
        load_strategy_config(write_cfg(root, params={"bogus": 1}), root)


def test_unknown_market_key_fails(root: Path):
    (root / "configs/market/nse_cash.yaml").write_text("slippage_bps_per_side: 10\nidle_cash_yield_annual: 0.0\nx: 1\n")
    with pytest.raises(ConfigError, match="x"):
        load_strategy_config(SMOKE, root)


def test_latest_dataset_rejected(root: Path):
    with pytest.raises(ConfigError, match="pinned"):
        load_strategy_config(write_cfg(root, dataset="nse_research@latest"), root)


def test_locked_period_needs_final(root: Path):
    cfg = load_strategy_config(write_cfg(root, period={"start": date(2010, 1, 4), "end": date(2025, 1, 1)}), root)
    with pytest.raises(ConfigError, match="locked"):
        enforce_lock(cfg, final=False)
    enforce_lock(cfg, final=True)


def test_cli_reports_config_error_cleanly(root: Path):
    res = CliRunner().invoke(app, ["backtest", str(write_cfg(root, extra_key=1)), "--root", str(root)])
    assert res.exit_code == 2 and "error:" in res.output
