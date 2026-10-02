"""M25: runs before the Nifty 500 TRI file starts (2010-01-04) leave that baseline empty instead of failing."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from mb.config.loader import load_baselines
from mb.evaluation.baselines import _covers, buy_and_hold_curve

ROOT = Path(__file__).resolve().parents[1]


def test_the_tri_covers_the_development_period_but_not_2007():
    tri = buy_and_hold_curve(ROOT, load_baselines(ROOT))
    assert _covers(tri, date(2010, 1, 4))
    assert not _covers(tri, date(2007, 4, 2))
