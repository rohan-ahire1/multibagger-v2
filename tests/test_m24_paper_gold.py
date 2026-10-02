"""M24: the paper book runs a fixed-weight (gold) sleeve and matches its backtest replay."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
from test_m3_sepa import _cfg, _market
from test_m6_paper import _days, _hol, _panel, _paper_cfg, _view
from test_m19_momentum import _m19

from mb.config.loader import Resolved, load_paper_config
from mb.config.models import Period, StrategyConfig
from mb.live.paper import Book, Store, advance, check_supported
from mb.live.replay import replay

ROOT = Path(__file__).resolve().parents[1]
PORT = {"top_n": 2, "hold_rank_max": 2, "inverse_vol_sessions": 20}


def _strat(**port) -> Resolved:
    s = StrategyConfig(name="momentum", version="t", dataset="x@1", market="m",
                       period=Period(start=date(2020, 1, 1), end=date(2020, 1, 2)), params={})
    p = _m19({"GOLD": 0.2}, portfolio=PORT | port, universe={"adv_window_sessions": 5},
             ranking={"lookback_sessions": 40, "skip_sessions": 5})
    return Resolved(s, p, _market(True), _cfg("x"), Path("s.yaml"))


def _gold_panel(days, drop: set[date] = frozenset()) -> pl.DataFrame:
    panel = _panel(days, {"AAA": 0.004, "BBB": 0.002, "CCC": -0.001, "DDD": 0.003, "GOLD": 0.001})
    panel = panel.with_columns(pl.when(pl.col("symbol") == "GOLD").then(pl.lit("isin:INFGOLD"))
                               .otherwise(pl.col("security_id")).alias("security_id"))
    return panel.filter(~((pl.col("symbol") == "GOLD") & pl.col("date").is_in(sorted(drop))))


def _run(tmp_path, panel, days, **port):
    cfg, strat = _paper_cfg(date(2023, 8, 1), initial_capital=1e7), _strat(**port)
    store = Store(tmp_path, cfg.name)
    book, recs, _ = advance(Book(None, cfg.initial_capital), cfg, strat, _view(panel), _hol(days), store)
    return cfg, strat, store, book, recs


def test_the_paper_book_holds_the_sleeve_and_matches_the_replay(tmp_path):
    days = _days(date(2023, 6, 1), 200)
    panel = _gold_panel(days)
    cfg, strat, store, book, recs = _run(tmp_path, panel, days)
    decisions = [r["decision"] for r in recs if r["decision"]]
    assert len(decisions) >= 5
    for d in decisions:
        assert "GOLD" in d["picks"] and len(d["picks"]) == 3 and d["weights"]["GOLD"] == 0.2
    assert "GOLD" in book.positions
    gold = book.positions["GOLD"].shares * book.positions["GOLD"].last_close / book.equity()
    assert 0.15 < gold < 0.25
    rep = replay(cfg, strat, _view(panel), store.days())
    assert rep["decision_mismatches"] == [] and rep["ok"]


def test_a_sleeve_with_no_bar_on_the_decision_day_is_sized_off_its_last_close(tmp_path):
    days = _days(date(2023, 6, 1), 200)
    month_ends = [d for d, n in zip(days, days[1:]) if n.month != d.month and d >= date(2023, 8, 1)]
    panel = _gold_panel(days, {month_ends[1]})
    _, _, _, _, recs = _run(tmp_path, panel, days)
    rec = next(r for r in recs if r["session"] == month_ends[1].isoformat())
    last = panel.filter((pl.col("symbol") == "GOLD") & (pl.col("date") < month_ends[1]))["close"][-1]
    gold = [o for o in rec["decision"]["orders"] if o["symbol"] == "GOLD"]
    assert "GOLD" in rec["decision"]["picks"] and gold and all(o["ref_price"] == last for o in gold)


def test_the_draft_gold_paper_config_pins_the_m19_reference():
    cfg, strat = load_paper_config(ROOT / "configs/paper/momentum_top40_gold.yaml", ROOT)
    assert strat.strategy.version == "m19_gold20_invvol_b2"
    check_supported(strat.params)


def test_the_draft_adv2cr_paper_config_pins_the_m33_reference():
    cfg, strat = load_paper_config(ROOT / "configs/paper/momentum_top40_gold_adv2cr.yaml", ROOT)
    assert strat.strategy.version == "m33_adv2cr_gold20_b2" and strat.params.universe.min_adv_inr == 20_000_000
    check_supported(strat.params)
