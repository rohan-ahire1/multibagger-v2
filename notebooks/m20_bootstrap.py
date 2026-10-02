"""M20 (docs/research/m20.md): the M17 bootstrap applied to the M19 gold sleeve.

A = gold20, B = the pin m16_invvol_b2, C = gold30, D = 12-1 momentum, E = Nifty 500 TRI.
Run: uv run python notebooks/m20_bootstrap.py. Settings are the pre-registered ones in m20.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.evaluation.baselines import buy_and_hold_curve, momentum_curve

ROOT = Path(__file__).resolve().parents[1]
RUNS = {"A": "20260929-202720-5f07ff7a", "B": "20260929-195717-eb7a8fe9", "C": "20260929-202729-cdf2da26"}
BLOCK, N, SEED, CHUNK = 63, 5000, 20260930, 250

cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m16_invvol_b2.yaml", ROOT)
per = cfg.strategy.period
curves = {k: pl.read_parquet(ROOT / f"runs/{r}/equity.parquet").select("date", "equity") for k, r in RUNS.items()}
panel = datasets.dataset_path(ROOT, cfg.strategy.dataset) / datasets.PANEL_FILE
curves["D"] = momentum_curve(cfg.baselines, cfg.market, panel, per.start, per.end)[0].select("date", "equity")
days = curves["A"].filter(pl.col("date").is_between(per.start, per.end)).select("date")
tri = buy_and_hold_curve(ROOT, cfg.baselines).select("date", "equity").sort("date")
curves["E"] = days.join_asof(tri, on="date", strategy="backward")

eq = np.column_stack([days.join(curves[k], on="date", how="left")["equity"].to_numpy() for k in "ABCDE"])
assert not np.isnan(eq).any()
rets = eq[1:] / eq[:-1] - 1
years = (days["date"][-1] - days["date"][0]).days / 365.25
T = rets.shape[0]


def stats(r: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """r: (..., T, 5) daily returns -> CAGR %, max DD %, Calmar, each (..., 5)."""
    path = np.cumprod(1 + r, axis=-2)
    path = np.concatenate([np.ones_like(path[..., :1, :]), path], axis=-2)
    cagr = (path[..., -1, :] ** (1 / years) - 1) * 100
    dd = (1 - path / np.maximum.accumulate(path, axis=-2)).max(axis=-2) * 100
    return cagr, dd, cagr / dd


cagr0, dd0, cal0 = stats(rets)
for i, k in enumerate("ABCDE"):
    print(f"actual {k}: CAGR {cagr0[i]:.2f}% max DD {dd0[i]:.2f}% Calmar {cal0[i]:.3f}")
for k, r in RUNS.items():
    s = json.loads((ROOT / f"runs/{r}/metrics.json").read_text())["strategy"]
    i = "ABC".index(k)
    assert abs(s["calmar"] - cal0[i]) < 5e-3, (k, s["calmar"], cal0[i])
corr = np.corrcoef(rets.T)

rng = np.random.default_rng(SEED)
cal, cg = [], []
for _ in range(N // CHUNK):
    # stationary bootstrap: start a new block with probability 1/BLOCK, else continue the previous index
    start = rng.integers(0, T, size=(CHUNK, T))
    new = rng.random((CHUNK, T)) < 1 / BLOCK
    new[:, 0] = True
    idx = np.empty((CHUNK, T), dtype=np.int64)
    idx[:, 0] = start[:, 0]
    for t in range(1, T):
        idx[:, t] = np.where(new[:, t], start[:, t], (idx[:, t - 1] + 1) % T)
    c, _, k = stats(rets[idx])
    cal.append(k)
    cg.append(c)
cal, cg = np.concatenate(cal), np.concatenate(cg)

for j, k in enumerate("BCDE", start=1):
    d, g = cal[:, 0] - cal[:, j], cg[:, 0] - cg[:, j]
    print(f"A vs {k}: corr {corr[0, j]:.3f}; actual Calmar diff {cal0[0] - cal0[j]:+.3f}; A higher in {np.mean(d > 0):.1%}; "
          f"Calmar diff 5-95% [{np.quantile(d, .05):+.3f}, {np.quantile(d, .95):+.3f}]; "
          f"CAGR diff 5-95% [{np.quantile(g, .05):+.2f}, {np.quantile(g, .95):+.2f}] pts, A higher CAGR in {np.mean(g > 0):.1%}")
for j, k in enumerate("ABCDE"):
    print(f"{k}: Calmar 5-50-95% {np.quantile(cal[:, j], .05):.3f} / {np.median(cal[:, j]):.3f} / {np.quantile(cal[:, j], .95):.3f}")
