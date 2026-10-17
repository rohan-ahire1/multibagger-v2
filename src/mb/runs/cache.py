"""Write-once file cache under `data/cache/` for pieces that many runs build the same way.

A key holds everything the piece depends on plus a hash of the `mb` source and the polars and numpy versions, so any
change to them starts a fresh entry; old entries are never changed. Inside `off()` nothing is read or written, which is
how `mb runs verify` re-computes a whole result.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

import mb
from mb.data import datasets

ROOT = Path("data") / "cache"
_on = True


@contextmanager
def off() -> Iterator[None]:
    global _on
    before, _on = _on, False
    try:
        yield
    finally:
        _on = before


def enabled() -> bool:
    return _on


@functools.cache
def code_hash() -> str:
    h = hashlib.sha256(f"polars {pl.__version__} numpy {np.__version__}".encode())
    pkg = Path(mb.__file__).parent
    for p in sorted(pkg.rglob("*.py")):
        h.update(p.relative_to(pkg).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def key(**parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts | {"code": code_hash()}, sort_keys=True, default=str).encode()).hexdigest()


def panel_sha(panel_path: Path) -> str | None:
    """The panel's sha256 from its dataset manifest; None for a panel outside a dataset (a test panel is not cached)."""
    try:
        return datasets.read_manifest(panel_path.parent)["outputs"][datasets.PANEL_FILE]["sha256"]
    except FileNotFoundError:
        return None


def write_once(path: Path, write: Callable[[Path], None]) -> None:
    """Write to a temp name in the same folder, then rename: parallel runs may build the same entry at once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    write(tmp)
    tmp.replace(path)
