"""M40: NSE delivery-position files, and dropping the eligible names with the lowest delivery share."""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError
from test_m5_momentum import _days, _frame
from test_m32_momentum import _m32

from mb.live.paper import check_supported
from mb.sources import nse_delivery
from mb.strategy.momentum.params import ParamsM40
from mb.strategy.momentum.targets import ranked


def _m40(frac: float | None) -> ParamsM40:
    p = _m32(None).model_dump()
    p["universe"] |= {"delivery_drop_frac": frac}
    p["ranking"] |= {"lookback_sessions": 10, "skip_sessions": 1, "score": "return"}
    return ParamsM40.model_validate(p)


def test_parse_reads_records_only(tmp_path: Path):
    f = tmp_path / "2012" / "2012-02-01.DAT"
    f.parent.mkdir()
    f.write_text("Security Wise Delivery Position - Compulsory Rolling Settlement\n10,MTO,01022012,436385455,0001435\n"
                 "Trade Date <01-FEB-2012>,Settlement Type <N>\nRecord Type,Sr No,Name of Security,Quantity Traded,"
                 "Deliverable Quantity,% of Deliverable\n20,1,20MICRONS,EQ,113043,27490,24.32\n20,2,ABC,BE,10,10,100.00\n")
    got = nse_delivery.parse_all(tmp_path, None)
    assert got.filter(pl.col("symbol") == "20MICRONS").select("series", "traded_qty", "deliv_qty").row(0) == ("EQ", 113043, 27490)


def _panel(share: dict[str, float | None]) -> tuple[pl.DataFrame, list]:
    # A rises fastest, then B, C, D, E; each trades 1,000 shares a day with the given delivery share.
    days = _days(30)
    rates = {"A": 1.010, "B": 1.008, "C": 1.006, "D": 1.004, "E": 1.002}
    panel = _frame({s: [100.0 * g ** i for i in range(30)] for s, g in rates.items()}, days)
    return panel.with_columns(pl.lit(1000).alias("volume"),
                              pl.col("symbol").replace_strict(share, return_dtype=pl.Float64).mul(1000).cast(pl.Int64)
                              .alias("deliv_qty")), days


def test_the_lowest_delivery_share_is_dropped_and_missing_delivery_is_not_eligible():
    panel, days = _panel({"A": 0.2, "B": 0.6, "C": 0.5, "D": 0.4, "E": None})
    d = days[-1]
    p = _m40(0.2)
    # E has no delivery record: not eligible. Of A-D, ceil(0.2 * 4) = 1 name goes: A (0.2).
    assert ranked(panel, p.universe, p.ranking, d, d)[d] == ["B", "C", "D"]
    off = _m40(None)
    assert ranked(panel.drop("volume", "deliv_qty"), off.universe, off.ranking, d, d)[d] == ["A", "B", "C", "D", "E"]


def test_the_share_uses_only_sessions_with_a_record():
    panel, days = _panel({"A": 0.2, "B": 0.6, "C": 0.5, "D": 0.4, "E": 0.45})
    # B's records go missing on half its days; its share over the rest is still 0.6, so D (0.4) is dropped after A.
    gap = (pl.col("symbol") == "B") & pl.col("date").is_in(days[::2])
    panel = panel.with_columns(pl.when(gap).then(None).otherwise(pl.col("deliv_qty")).alias("deliv_qty"))
    d = days[-1]
    p = _m40(0.4)
    assert ranked(panel, p.universe, p.ranking, d, d)[d] == ["B", "C", "E"]


def test_option_is_validated_and_accepted_by_paper():
    with pytest.raises(ValidationError, match="delivery_drop_frac"):
        _m40(1.0)
    check_supported(_m40(0.2))  # M43: the paper book reads delivery (tests/test_m43_paper_delivery.py)
    with pytest.raises(ValueError, match="portfolio.vol_states"):
        p = _m32({"vol_sessions": 5, "high_quantile": 0.8, "min_history_months": 3})
        check_supported(p)


def test_m33_configs_keep_their_model_and_m40_configs_route_to_m40():
    from mb.config.loader import load_strategy_config
    from mb.strategy.momentum.params import ParamsM19
    root = Path(__file__).resolve().parents[1]
    assert type(load_strategy_config(root / "strategies/momentum/configs/m33_adv2cr_gold20_b2.yaml", root).params) is ParamsM19
    for n, f in (("base", None), ("deliv20", 0.2), ("deliv40", 0.4)):
        cfg = load_strategy_config(root / f"strategies/momentum/configs/m40_{n}_gold20_b2.yaml", root)
        assert type(cfg.params) is ParamsM40 and cfg.params.universe.delivery_drop_frac == f
