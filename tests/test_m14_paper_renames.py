"""M14 in paper trading: on a rename-linked daily dataset, a held name and its orders follow the rename."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
from test_m6_paper import _days, _hol, _panel, _paper_cfg, _strat, _view

from mb.config.loader import load_data_config, load_paper_config
from mb.config.models import DataConfigM14
from mb.live.paper import Book, DataView, Position, Store, _renames, advance
from mb.live.replay import replay

ROOT = Path(__file__).resolve().parents[1]


def _linked(view: DataView, renames: dict[str, list[tuple[date, str]]]) -> DataView:
    return DataView(view.ref, view.panel_sha256, view.panel, view.share_mult, view.jumps, renames)


def test_a_held_name_is_carried_through_a_rename_and_the_replay_still_matches(tmp_path):
    days = _days(date(2023, 6, 1), 200)
    k = 150  # AAA's last session under its old symbol; ZZZ from days[k + 1]
    drifts = {"AAA": 0.004, "BBB": 0.002, "CCC": -0.001, "DDD": 0.003, "EEE": 0.0}
    panel = _panel(days, drifts)
    before = days[k + 1]
    # Yesterday's dataset: the new symbol is not out yet. Today's (linked): AAA's rows all carry ZZZ.
    old = _view(panel.filter(pl.col("date") <= days[k]))
    new = _linked(_view(panel.with_columns(pl.when(pl.col("symbol") == "AAA").then(pl.lit("ZZZ"))
                                           .otherwise(pl.col("symbol")).alias("symbol"))), {"AAA": [(before, "ZZZ")]})
    cfg, strat = _paper_cfg(date(2023, 8, 1)), _strat(True, portfolio={"top_n": 2, "hold_rank_max": 2})
    store = Store(tmp_path, cfg.name)
    book, _, _ = advance(Book(None, cfg.initial_capital), cfg, strat, old, _hol(days), store)
    assert "AAA" in book.positions
    shares = book.positions["AAA"].shares
    book, recs, notes = advance(book, cfg, strat, new, _hol(days), store)
    assert recs[0]["corporate_actions"][0] == {"symbol": "ZZZ", "kind": "rename", "from": "AAA", "shares": shares}
    assert "AAA" not in book.positions and not any("no trade" in n for n in notes)
    rep = replay(cfg, strat, new, store.days())
    assert rep["decision_mismatches"] == [] and rep["ok"]


def test_pending_orders_follow_a_rename_and_a_reused_old_symbol_stays_put():
    days = _days(date(2024, 3, 4), 4)
    view = _linked(_view(_panel(days, {"NEW": 0.0, "OLD": 0.0})), {"OLD": [(days[2], "NEW")]})
    book = Book(days[1], 0.0, {"OLD": Position(10, days[0], 1000.0, 0.0, 100.0, days[1])},
                {"decided": days[1].isoformat(), "orders": [{"symbol": "OLD", "side": "sell", "shares": 10}]})
    done = _renames(book, view, [])
    assert set(book.positions) == {"NEW"} and book.pending["orders"][0]["symbol"] == "NEW"
    assert [d["kind"] for d in done] == ["rename", "rename_order"]
    # OLD bought on or after the link's date is a later company with the same ticker: not moved.
    later = Book(days[3], 0.0, {"OLD": Position(5, days[2], 500.0, 0.0, 100.0, days[3])},
                 {"decided": days[3].isoformat(), "orders": [{"symbol": "OLD", "side": "sell", "shares": 5}]})
    assert _renames(later, view, []) == [] and set(later.positions) == {"OLD"}


def test_an_unlinked_view_changes_nothing():
    days = _days(date(2024, 3, 4), 2)
    view = _view(_panel(days, {"AAA": 0.0}))
    book = Book(days[0], 0.0, {"AAA": Position(1, days[0], 100.0, 0.0, 100.0, days[0])})
    assert _renames(book, view, []) == [] and view.renamed("AAA", days[0]) == "AAA"


def test_the_draft_book_reads_linked_daily_data_under_its_own_name():
    cfg, _ = load_paper_config(ROOT / "configs/paper/momentum_top40_invvol.yaml", ROOT)
    linked, _ = load_data_config(ROOT / cfg.data_config)
    plain, _ = load_data_config(ROOT / "configs/data/nse_daily.yaml")
    assert isinstance(linked, DataConfigM14) and linked.link_renames_by_isin and linked.name != plain.name
    assert linked.model_dump(exclude={"name", "link_renames_by_isin", "rename_max_gap_days"}) == plain.model_dump(exclude={"name"})
