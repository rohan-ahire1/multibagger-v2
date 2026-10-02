"""M104 (docs/research/m104.md): deflated Sharpe ratio of the lead books given every 2010-23 run tried (information).

Bailey & Lopez de Prado (2014): the probability that the true Sharpe ratio is above zero after allowing for the best
of N trials, skew and fat tails. Trials = every momentum or blend run on 2010-01-04..2023-12-31 in runs/, one per
config hash (5 bps and 25 bps both count). The expected best Sharpe under no skill is
SR0 = sd(SR) x ((1 - g) z(1 - 1/N) + g z(1 - 1/(N e))), g = Euler's constant. Trials are highly correlated, so N is
also shown as an effective count N / (1 + (N - 1) rho), rho = the mean pairwise correlation of daily returns.
Run: uv run python notebooks/m104_deflated_sharpe.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import polars as pl
from statistics import NormalDist

ND = NormalDist()


def skew(x: np.ndarray) -> float:
    z = (x - x.mean()) / x.std()
    return float((z ** 3).mean())


def kurtosis(x: np.ndarray) -> float:
    z = (x - x.mean()) / x.std()
    return float((z ** 4).mean())


ROOT = Path(__file__).resolve().parents[1]
LEADS = {"m95 tranches": "20261002-041639-baa42e53", "m102 s075 tranches": "20261002-045215-4e3e6d98",
         "m98 t20 tranches": "20261002-043350-fef356b4", "pin m49_b_b2": "20261002-000607-0103cc7f",
         "pin tranches": "20261002-001643-d6a3c453"}

rets: dict[str, np.ndarray] = {}
dates = None
for d in sorted((ROOT / "runs").iterdir()):
    m = d / "manifest.json"
    if not m.exists() or not (d / "equity.parquet").exists():
        continue
    man = json.loads(m.read_text())
    if man["period"] != ["2010-01-04", "2023-12-31"] or man["final"] or not man["strategy"].split("/")[0] in ("momentum", "blend"):
        continue
    if man["config_hash"] in rets and d.name not in LEADS.values():
        continue
    e = pl.read_parquet(d / "equity.parquet").select("date", "equity").sort("date")
    if dates is None:
        dates = e["date"]
    if e.height != len(dates) or not (e["date"] == dates).all():
        continue
    r = (e["equity"] / e["equity"].shift(1) - 1).drop_nulls().to_numpy()
    rets[d.name if d.name in LEADS.values() else man["config_hash"]] = r

keys = list(rets)
R = np.vstack([rets[k] for k in keys])
sr = R.mean(axis=1) / R.std(axis=1, ddof=1)
N, T = len(keys), R.shape[1]
rho = (np.corrcoef(R).sum() - N) / (N * (N - 1))
g = 0.5772156649


def sr0(n: float) -> float:
    return float(np.std(sr, ddof=1) * ((1 - g) * ND.inv_cdf(1 - 1 / n) + g * ND.inv_cdf(1 - 1 / (n * math.e))))


neff = N / (1 + (N - 1) * rho)
print(f"trials N = {N}, days T = {T}, mean pairwise correlation {rho:.3f}, effective N {neff:.1f}")
print(f"trial daily Sharpe: mean {sr.mean():.4f}, sd {np.std(sr, ddof=1):.4f}; annualised x sqrt(250)")
print(f"expected best of N under no skill: SR0 {sr0(N) * 250 ** .5:.3f} (N) / {sr0(neff) * 250 ** .5:.3f} (effective N)")
for name, rid in LEADS.items():
    r = rets[rid]
    s = r.mean() / r.std(ddof=1)
    k, sk = kurtosis(r), skew(r)
    den = math.sqrt(1 - sk * s + (k - 1) / 4 * s * s)
    out = [ND.cdf((s - z) * math.sqrt(T - 1) / den) for z in (0.0, sr0(N), sr0(neff))]
    print(f"{name} ({rid}): annual Sharpe {s * 250 ** .5:.3f}, skew {sk:.2f}, kurtosis {k:.1f}; "
          f"PSR(0) {out[0]:.4f}, DSR(N) {out[1]:.4f}, DSR(effective N) {out[2]:.4f}")

# The relevant question: is the gain over the pin's tranches more than the best of N tries would give by luck?
# Same test on the daily return difference (lead minus pin tranches), trials = every run minus pin tranches.
base = rets[LEADS["pin tranches"]]
D = R - base
ok = np.abs(D).sum(axis=1) > 0
srd = D[ok].mean(axis=1) / D[ok].std(axis=1, ddof=1)
Nd = int(ok.sum())
rhod = (np.corrcoef(D[ok]).sum() - Nd) / (Nd * (Nd - 1))
neffd = Nd / (1 + (Nd - 1) * rhod)


def sr0d(n: float) -> float:
    return float(np.std(srd, ddof=1) * ((1 - g) * ND.inv_cdf(1 - 1 / n) + g * ND.inv_cdf(1 - 1 / (n * math.e))))


print(f"\nvs pin tranches: trials {Nd}, mean pairwise correlation {rhod:.3f}, effective N {neffd:.1f}; "
      f"SR0 {sr0d(Nd) * 250 ** .5:.3f} (N) / {sr0d(neffd) * 250 ** .5:.3f} (effective N), annualised")
for name in ("m95 tranches", "m102 s075 tranches", "m98 t20 tranches", "pin m49_b_b2"):
    r = rets[LEADS[name]] - base
    s = r.mean() / r.std(ddof=1)
    k, sk = kurtosis(r), skew(r)
    den = math.sqrt(1 - sk * s + (k - 1) / 4 * s * s)
    out = [ND.cdf((s - z) * math.sqrt(T - 1) / den) for z in (0.0, sr0d(Nd), sr0d(neffd))]
    print(f"{name} minus pin tranches: annual information ratio {s * 250 ** .5:.3f}, skew {sk:.2f}, kurtosis {k:.1f}; "
          f"PSR(0) {out[0]:.4f}, DSR(N) {out[1]:.4f}, DSR(effective N) {out[2]:.4f}")
