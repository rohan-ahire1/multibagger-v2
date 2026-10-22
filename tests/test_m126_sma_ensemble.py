"""M126: graded regime over several moving-average lengths."""
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from mb.config.loader import load_strategy_config
from mb.data import datasets
from mb.strategy.momentum.params import ParamsM126
from mb.strategy.momentum.targets import risk_on, targets

ROOT = Path(__file__).resolve().parents[1]


def test_configs_route_to_m126_and_lengths_must_be_distinct():
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m126_ens3.yaml", ROOT)
    assert isinstance(cfg.params, ParamsM126) and cfg.params.regime.extra_sma_sessions == [150, 250]
    with pytest.raises(ValidationError):
        cfg.params.regime.model_validate({**cfg.params.regime.model_dump(), "extra_sma_sessions": [200]})


def test_gross_is_the_share_of_lengths_risk_on():
    cfg = load_strategy_config(ROOT / "strategies/momentum/configs/m126_ens5.yaml", ROOT)
    path = datasets.dataset_path(ROOT, cfg.strategy.dataset) / datasets.PANEL_FILE
    if not path.exists():
        pytest.skip("dataset not on this machine")
    panel = pl.scan_parquet(path).filter(pl.col("date") <= date(2020, 6, 30)).collect()
    p = cfg.params.model_copy(update={"regime": cfg.params.regime.model_copy(update={"risk_off_symbol": None}),
                                      "portfolio": cfg.params.portfolio.model_copy(update={"fixed_weights": {}})})
    t = targets(panel, p, date(2019, 6, 1), date(2020, 6, 30))
    r = p.regime
    for d, x in t.items():
        f = sum(risk_on(panel, r.benchmark_symbol, n, [d])[d] for n in [r.sma_sessions, *r.extra_sma_sessions]) / 5
        assert x.gross == pytest.approx(f + (1 - f) * r.risk_off_gross)
