"""M120: up-limit hit count and the buy filter (src/mb/strategy/momentum/targets.py)."""
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from mb.config.loader import load_strategy_config
from mb.strategy.momentum.params import LimitHits
from mb.strategy.momentum.targets import limit_hits, targets

ROOT = Path(__file__).resolve().parents[1]
LH = dict(bands=[0.05, 0.10, 0.20], below=0.0025, above=0.001, sessions=3, max_hits=1)


def _panel(rows: dict[str, list[tuple[float, float]]]) -> pl.DataFrame:
    """rows: symbol -> [(close, high)]; adjusted = raw; dates are consecutive days from 2020-01-01."""
    out = []
    for s, bars in rows.items():
        for i, (c, h) in enumerate(bars):
            out.append({"date": date(2020, 1, 1) + timedelta(days=i), "symbol": s, "security_id": f"isin:INE{s}",
                        "series": "EQ", "close": c, "high": h, "adj_open": c, "adj_high": h, "adj_close": c,
                        "turnover": 1e9, "volume": 100, "deliv_qty": 50})
    return pl.DataFrame(out)


def test_counts_closes_at_high_on_a_band_within_the_window():
    # day 1: +5% at the high (hit); day 2: +10% but high above close (no); day 3: +19.9% at the high (hit);
    # day 4: +3% at the high (no band); day 5: -5% (no)
    p = _panel({"A": [(100, 100), (105, 105), (115.5, 116), (138.4845, 138.4845), (142.64, 142.64), (135.5, 140)]})
    d = sorted(p["date"].to_list())
    h = limit_hits(p, LimitHits(**LH), d)
    assert [h[x]["A"] for x in d] == [0, 1, 1, 2, 1, 1]  # rolling 3 sessions


def test_bad_settings_fail():
    with pytest.raises(ValidationError):
        LimitHits(**{**LH, "below": 0.06})
    with pytest.raises(ValidationError):
        LimitHits(**{**LH, "bands": []})


def test_new_buy_refused_held_name_kept():
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m120_lh20.yaml", ROOT)
    p = cfg.params
    p = p.model_copy(update={
        "universe": p.universe.model_copy(update={"min_price_inr": 1, "min_adv_inr": 1, "adv_window_sessions": 2,
                                                  "delivery_drop_frac": None, "max_gap_days": None}),
        "ranking": p.ranking.model_copy(update={"lookback_sessions": 3, "skip_sessions": 0, "score": "return"}),
        "portfolio": p.portfolio.model_copy(update={"top_n": 1, "hold_rank_max": 1, "weighting": "equal",
                                                    "fixed_weights": {}}),
        "regime": p.regime.model_copy(update={"enabled": False, "risk_off_symbol": None}),
        "limit_hits": LimitHits(**{**LH, "sessions": 40, "max_hits": 0}),
    })
    # B rises fastest but had a 5% limit hit on Jan 26, so it is refused in Jan and Feb and A (next) is bought.
    a = [(100 * 1.01 ** i, 100 * 1.01 ** i) for i in range(60)]
    b = [(100.0, 101.0)] * 25 + [(105.0, 105.0)] + [(105 * 1.02 ** i, 106 * 1.02 ** i) for i in range(1, 35)]
    c = [(100 * 1.005 ** i, 101 * 1.005 ** i) for i in range(60)]
    panel = _panel({"A": a, "B": b, "C": c})
    t = targets(panel, p, date(2020, 1, 5), date(2020, 2, 29))
    picks = {d: sorted(x.weights) for d, x in t.items()}
    assert picks[date(2020, 1, 31)] == ["A"]
    assert picks[date(2020, 2, 29)] == ["A"]
    off = targets(panel, p.model_copy(update={"limit_hits": None}), date(2020, 1, 5), date(2020, 2, 29))
    assert sorted(off[date(2020, 1, 31)].weights) == ["B"]
