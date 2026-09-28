"""Dataset versions: `data/datasets/<name>/<version>/` with a manifest. Versions are immutable."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import polars as pl

from mb.config.loader import ConfigError

PANEL_FILE = "panel.parquet"
OUTPUT_FILES = (PANEL_FILE, "ca_matches.parquet", "unexplained_jumps.parquet", "unusable_actions.parquet")
_REF = re.compile(r"^([a-z0-9_]+)@([A-Za-z0-9._-]+)$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def datasets_dir(root: Path) -> Path:
    return root / "data" / "datasets"


def split_ref(ref: str) -> tuple[str, str]:
    m = _REF.match(ref)
    if not m:
        raise ConfigError(f"dataset reference must look like <name>@<version>, got '{ref}'")
    return m.group(1), m.group(2)


def dataset_path(root: Path, ref: str) -> Path:
    name, version = split_ref(ref)
    return datasets_dir(root) / name / version


def read_manifest(path: Path) -> dict[str, Any]:
    return json.loads((path / "manifest.json").read_text())


def previous_version(root: Path, name: str, before: str) -> Path | None:
    base = datasets_dir(root) / name
    if not base.is_dir():
        return None
    versions = sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name < before)
    return base / versions[-1] if versions else None


def load_panel(root: Path, ref: str) -> pl.DataFrame:
    path = dataset_path(root, ref)
    if not (path / "manifest.json").is_file():
        raise ConfigError(f"dataset {ref} not found at {path}")
    return pl.read_parquet(path / PANEL_FILE)


def verify_outputs(path: Path) -> list[str]:
    """Return the names of output files whose hash differs from the manifest."""
    manifest = read_manifest(path)
    return [n for n, h in manifest["outputs"].items() if sha256_file(path / n) != h["sha256"]]


def remove_tmp(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
