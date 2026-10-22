"""M131: equal-risk-contribution weights among the picks (src/mb/strategy/momentum/targets.py)."""
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from mb.strategy.momentum.targets import erc, erc_weights


def test_risk_contributions_are_equal():
    rng = np.random.default_rng(1)
    a = rng.normal(size=(200, 6)) @ rng.normal(size=(6, 6))
    cov = np.cov(a, rowvar=False)
    w = erc(cov)
    rc = w * (cov @ w)
    assert w.sum() == pytest.approx(1.0) and (w > 0).all()
    assert rc / rc.sum() == pytest.approx(np.full(6, 1 / 6), abs=1e-8)


def test_equal_correlations_give_inverse_vol():
    sd = np.array([0.01, 0.02, 0.04])
    corr = np.full((3, 3), 0.3)
    np.fill_diagonal(corr, 1.0)
    w = erc(corr * np.outer(sd, sd))
    assert w == pytest.approx((1 / sd) / (1 / sd).sum())


def test_full_shrink_toward_the_mean_correlation_is_inverse_vol_on_a_panel():
    rng = np.random.default_rng(2)
    n = 40
    common = rng.normal(0, 0.01, n)
    rets = {"A": common + rng.normal(0, 0.01, n), "B": common + rng.normal(0, 0.01, n), "C": rng.normal(0, 0.03, n)}
    rows = []
    for s, r in rets.items():
        px = 100 * np.exp(np.concatenate([[0.0], np.cumsum(r)]))
        rows += [{"date": date(2020, 1, 1) + timedelta(days=i), "symbol": s, "adj_close": float(c)} for i, c in enumerate(px)]
    panel = pl.DataFrame(rows)
    d = date(2020, 1, 1) + timedelta(days=n)
    w0 = erc_weights(panel, 30, 0.0, {d: ["A", "B", "C"]})[d]
    w1 = erc_weights(panel, 30, 0.999999, {d: ["A", "B", "C"]})[d]
    win = np.array([np.diff(np.log(100 * np.exp(np.concatenate([[0.0], np.cumsum(r)]))))[-30:] for r in rets.values()])
    inv = 1 / win.std(axis=1, ddof=1)
    assert [w1[s] for s in "ABC"] == pytest.approx(list(inv / inv.sum()), rel=1e-4)
    assert w0["C"] > w1["C"]  # A and B move together, so the sample ERC gives the uncorrelated C more
