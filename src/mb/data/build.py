"""Build one immutable dataset version from the raw store."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from mb.config.loader import ConfigError
from mb.config.models import DataConfig, DataConfigM14
from mb.data import adjust, checks, datasets, renames
from mb.data.corporate_actions import load_actions, load_verified_moves
from mb.runs.record import git_state
from mb.sources import nse_bhavcopy


class CheckFailure(Exception):
    def __init__(self, results: list[checks.CheckResult]):
        self.results = results
        failed = [r for r in results if r.status == "fail"]
        super().__init__("data checks failed: " + "; ".join(
            f"{r.name}={r.value} (limit {r.limit}) {r.detail}".strip() for r in failed))


def _inputs(cfg: DataConfig, root: Path, zips: list[Path]) -> dict:
    h = hashlib.sha256()
    for z in zips:
        h.update(z.name.encode())
        h.update(datasets.sha256_file(z).encode())
    ca, ov = root / cfg.corporate_actions.raw_file, root / cfg.corporate_actions.overrides_file
    vm = root / cfg.corporate_actions.verified_moves_file
    return {
        "bhavcopy": {"files": len(zips), "first": zips[0].stem, "last": zips[-1].stem, "sha256": h.hexdigest()},
        "corporate_actions": {"file": cfg.corporate_actions.raw_file, "sha256": datasets.sha256_file(ca)},
        "overrides": {"file": cfg.corporate_actions.overrides_file, "sha256": datasets.sha256_file(ov)},
        "verified_moves": {"file": cfg.corporate_actions.verified_moves_file, "sha256": datasets.sha256_file(vm)},
    }


def build(cfg: DataConfig, cfg_hash: str, root: Path, version: str) -> Path:
    out = datasets.datasets_dir(root) / cfg.name / version
    if out.exists():
        raise ConfigError(f"dataset {cfg.name}@{version} already exists; versions are immutable")
    started = datetime.now(UTC)

    raw_dir = root / cfg.bhavcopy.raw_dir
    zips = nse_bhavcopy.build_zips(raw_dir, cfg.bhavcopy)
    bars = nse_bhavcopy.parse_all(raw_dir, cfg.bhavcopy)
    max_date = bars["date"].max()
    links = refused = None
    if isinstance(cfg, DataConfigM14) and cfg.link_renames_by_isin:
        links, refused = renames.rename_links(bars, cfg.rename_max_gap_days)
        bars = renames.relabel(bars, links, "date").sort(["symbol", "date"])

    actions = load_actions(cfg.corporate_actions, root, max_date, bars, links)
    if cfg.bhavcopy.first_date is not None:
        # An action on or before the first session has no prior bar to show it and moves no kept row's adjustment.
        actions = actions.filter(pl.col("ex_date") > bars["date"].min())
    events, unusable = adjust.expected_share_events(actions)
    matches = adjust.match_share_events(bars, events, cfg.adjustment)
    dividends = adjust.dividend_steps(bars, actions, cfg.adjustment)
    panel = adjust.build_research_panel(bars, matches, dividends)
    verified = load_verified_moves(root / cfg.corporate_actions.verified_moves_file)
    if links is not None:
        verified = renames.relabel(verified, links, "date")
    if cfg.bhavcopy.first_date is not None:
        verified = verified.filter(pl.col("date") > bars["date"].min())
    jumps = adjust.unexplained_jumps(panel, cfg.adjustment, verified)

    prev = datasets.previous_version(root, cfg.name, version)
    prev_rows = datasets.read_manifest(prev)["rows"] if prev else None
    results = checks.run_checks(panel, matches, unusable, jumps, len(zips), prev_rows, cfg.checks)
    if any(r.status == "fail" for r in results):
        raise CheckFailure(results)

    tmp = out.with_name(f".{version}.tmp")
    datasets.remove_tmp(tmp)
    tmp.mkdir(parents=True)
    tables = {
        datasets.PANEL_FILE: panel,
        "ca_matches.parquet": matches,
        "unexplained_jumps.parquet": jumps.sort(["symbol", "date"]),
        "unusable_actions.parquet": unusable,
    }
    if links is not None and refused is not None:
        tables |= {"rename_links.parquet": links, "rename_links_refused.parquet": refused}
    for name, table in tables.items():
        table.write_parquet(tmp / name, compression="zstd")
    manifest = {
        "dataset": f"{cfg.name}@{version}",
        "rows": panel.height,
        "symbols": panel["symbol"].n_unique(),
        "sessions": panel["date"].n_unique(),
        "date_min": panel["date"].min().isoformat(),
        "date_max": max_date.isoformat(),
        "columns": panel.columns,
        "config_hash": cfg_hash,
        "code": git_state(root),
        "inputs": _inputs(cfg, root, zips),
        "share_event_status": dict(sorted(matches.group_by("status").len().iter_rows())),
        "actions_resymbolled_by_isin": actions.filter(pl.col("feed_symbol").is_not_null()
                                                      & (pl.col("feed_symbol") != pl.col("symbol"))).height,
        "verified_moves": verified.height,
        **({"rename_links": links.height, "rename_links_refused": dict(sorted(refused.group_by("reason").len().iter_rows()))}
           if links is not None and refused is not None else {}),
        "checks": [r.as_dict() for r in results],
        "outputs": {n: {"sha256": datasets.sha256_file(tmp / n), "rows": t.height} for n, t in tables.items()},
        "built_at": started.isoformat(),
        "duration_s": round((datetime.now(UTC) - started).total_seconds(), 1),
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    tmp.rename(out)
    return out
