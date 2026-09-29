"""M14: a renamed stock's bars are relabelled to its later symbol, by ISIN; data config routing."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from mb.config.loader import load_data_config
from mb.config.models import DataConfig, DataConfigM14
from mb.data.renames import relabel, rename_links

ROOT = Path(__file__).resolve().parents[1]
D0 = date(2020, 1, 1)


def _bars(spec: list[tuple[str, str, int, int]]) -> pl.DataFrame:
    """(symbol, security_id, first day, last day) -> one bar per day, close = day number."""
    rows = [(D0 + timedelta(days=i), s, sid, float(i)) for s, sid, a, b in spec for i in range(a, b + 1)]
    return pl.DataFrame(rows, schema=["date", "symbol", "security_id", "close"], orient="row").sort("symbol", "date")


def test_a_rename_moves_the_old_bars_and_their_fallback_history_to_the_new_symbol():
    bars = _bars([("OLD", "fallback:OLD:EQ", 0, 4), ("OLD", "isin:INE1", 5, 9), ("NEW", "isin:INE1", 10, 14),
                  ("OTHER", "isin:INE2", 0, 14)])
    links, refused = rename_links(bars, 31)
    assert links.select("old", "new", "final", "before").rows() == [("OLD", "NEW", "NEW", D0 + timedelta(days=10))]
    assert refused.is_empty()
    out = relabel(bars, links, "date")
    assert out.filter(pl.col("symbol") == "NEW").sort("date")["close"].to_list() == [float(i) for i in range(15)]
    assert set(out["symbol"]) == {"NEW", "OTHER"}


def test_chains_follow_through_an_isin_change():
    # A -> B on INE1; B's split gives INE3; B -> C on INE3.
    bars = _bars([("A", "isin:INE1", 0, 4), ("B", "isin:INE1", 5, 7), ("B", "isin:INE3", 8, 9), ("C", "isin:INE3", 10, 12)])
    links, _ = rename_links(bars, 31)
    assert dict(links.select("old", "final").rows()) == {"A": "C", "B": "C"}
    assert relabel(bars, links, "date")["symbol"].unique().to_list() == ["C"]


def test_overlapping_spans_and_clashing_bars_are_refused():
    # OVL: both symbols carry INE1 on day 5. CLASH: the new symbol already had bars (another ISIN) on the old one's days.
    bars = _bars([("P", "isin:INE1", 0, 5), ("Q", "isin:INE1", 5, 9),
                  ("X", "isin:INE2", 0, 4), ("Y", "isin:INE9", 2, 3), ("Y", "isin:INE2", 5, 9)])
    links, refused = rename_links(bars, 31)
    assert links.is_empty()
    assert sorted(refused.select("old", "reason").rows()) == [("P", "overlap"), ("X", "two bars on one session")]


def test_a_link_across_a_long_gap_is_refused():
    bars = _bars([("OLD", "isin:INE1", 0, 4), ("NEW", "isin:INE1", 40, 44)])
    links, refused = rename_links(bars, 31)
    assert links.is_empty()
    assert refused.select("old", "new", "reason").rows() == [("OLD", "NEW", "gap")]
    assert rename_links(bars, 36)[0].height == 1


def test_keys_on_the_link_date_move_too():
    bars = _bars([("OLD", "isin:INE1", 0, 4), ("NEW", "isin:INE1", 5, 9)])
    links, _ = rename_links(bars, 31)
    keys = pl.DataFrame({"symbol": ["OLD", "OLD", "NEW"], "ex_date": [D0 + timedelta(days=2), D0 + timedelta(days=5),
                                                                      D0 + timedelta(days=7)]})
    assert relabel(keys, links, "ex_date")["symbol"].to_list() == ["NEW", "NEW", "NEW"]


def test_existing_data_configs_keep_their_model_and_the_linked_one_routes_to_m14():
    cfg, _ = load_data_config(ROOT / "configs/data/nse_research.yaml")
    assert type(cfg) is DataConfig
    linked, _ = load_data_config(ROOT / "configs/data/nse_research_linked.yaml")
    assert type(linked) is DataConfigM14 and linked.link_renames_by_isin
    assert linked.model_dump(exclude={"link_renames_by_isin", "rename_max_gap_days"}) == cfg.model_dump()
