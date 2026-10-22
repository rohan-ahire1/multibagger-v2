"""M135: the paper book decides N sessions before each month-end, and matches the backtest at that offset
(docs/research/m135.md)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import yaml
from test_m6_paper import _days, _hol, _paper_cfg, _view
from test_m106_paper_regime import _regime_panel, _strat

from mb.config.loader import Resolved, load_strategy_config
from mb.live import calendar
from mb.live.paper import Book, Store, advance, check_supported
from mb.live.replay import replay
from mb.strategy.momentum.params import ParamsM89
from mb.strategy.momentum.targets import decision_dates, targets

ROOT = Path(__file__).resolve().parents[1]
OFF = 5


def _offset_strat(n: int) -> Resolved:
    s = _strat()
    p = s.params.model_dump()
    p["schedule"]["decision_offset_sessions"] = n
    return Resolved(s.strategy, ParamsM89.model_validate(p), s.market, s.baselines, s.strategy_path)


def _expected(days: list[date], n: int) -> list[date]:
    """The sessions in `days` with n trading days of their month after them (by the test calendar)."""
    return [d for d in days if calendar.sessions_left_in_month(d, _hol(days)) == n]


def test_sessions_left_in_month_skips_weekends_and_holidays():
    hol = {date(2026, 10, 30), date(2026, 10, 2)}
    assert calendar.sessions_left_in_month(date(2026, 10, 29), hol) == 0
    assert calendar.sessions_left_in_month(date(2026, 10, 22), hol) == 5  # 23, 26, 27, 28, 29
    assert calendar.sessions_left_in_month(date(2026, 9, 30), hol) == 0


def test_open_end_makes_the_last_known_session_the_decision_day():
    days = _days(date(2024, 1, 1), 50)  # January, February and part of March
    panel = pl.DataFrame({"date": days})
    full = decision_dates(panel, days[0], days[-1], OFF)
    assert full[:2] == _expected(days, OFF)[:2]
    cut = [d for d in days if d <= date(2024, 3, 5)]
    opened = decision_dates(panel.filter(pl.col("date") <= cut[-1]), days[0], cut[-1], OFF, open_end=True)
    assert opened == _expected(days, OFF)[:2] + [cut[-1]]
    assert decision_dates(panel, days[0], days[-1], 0, open_end=True) == decision_dates(panel, days[0], days[-1], 0)


def test_the_offset_book_decides_n_sessions_before_month_end_and_matches_the_backtest(tmp_path):
    days = _days(date(2023, 6, 1), 220)
    panel = _regime_panel(days)
    cfg, strat = _paper_cfg(date(2023, 8, 1), initial_capital=1e7), _offset_strat(OFF)
    check_supported(strat.params)
    store = Store(tmp_path, cfg.name)
    book, recs, notes = advance(Book(None, cfg.initial_capital), cfg, strat, _view(panel), _hol(days), store)
    made = [date.fromisoformat(r["session"]) for r in recs if r["decision"]]
    assert made == [d for d in _expected(days, OFF) if d >= cfg.start]
    assert not [n for n in notes if "following the data" in n]
    bt = targets(panel, strat.params, cfg.start, days[-1])
    for r in recs:
        if r["decision"]:
            t = bt[date.fromisoformat(r["session"])]
            total = sum(t.weights.values())
            assert sorted(t.weights) == r["decision"]["picks"]
            assert all(abs(w - t.weights[k] / total) < 1e-12 for k, w in r["decision"]["weights"].items())
    rep = replay(cfg, strat, _view(panel), store.days())
    assert rep["decision_mismatches"] == [] and rep["ok"]


def test_day_by_day_runs_decide_on_the_calendar_alone_and_replay_mid_month(tmp_path):
    """Live, the data never reaches the next month on the decision day: the calendar decides, and the replay in the
    open month (after the book's decision, before the month ends) still matches."""
    days = _days(date(2023, 6, 1), 172)  # ends Fri 2024-01-26, two sessions after the January decision (Wed 24th)
    panel = _regime_panel(days)
    cfg, strat = _paper_cfg(date(2023, 8, 1), initial_capital=1e7), _offset_strat(OFF)
    store = Store(tmp_path, cfg.name)
    book = Book(None, cfg.initial_capital)
    for d in (d for d in days if d >= date(2023, 7, 20)):
        book, _, _ = advance(book, cfg, strat, _view(panel.filter(pl.col("date") <= d)), _hol(days), store)
    made = [date.fromisoformat(r["session"]) for r in store.days() if r["decision"]]
    last_month = (days[-1].year, days[-1].month)
    want = [d for d in _expected(days, OFF) if d >= cfg.start and (d.year, d.month) != last_month]
    assert made == want + [date(2024, 1, 24)] and days[-1] == date(2024, 1, 26)
    rep = replay(cfg, strat, _view(panel), store.days())
    assert rep["decision_mismatches"] == [] and rep["ok"]


def test_month_end_book_unchanged_by_the_offset_support(tmp_path):
    days = _days(date(2023, 6, 1), 220)
    panel = _regime_panel(days)
    cfg, strat = _paper_cfg(date(2023, 8, 1), initial_capital=1e7), _strat()
    _, recs, _ = advance(Book(None, cfg.initial_capital), cfg, strat, _view(panel), _hol(days), Store(tmp_path, "t"))
    assert all("decision_day" not in r for r in recs)
    made = [date.fromisoformat(r["session"]) for r in recs if r["decision"]]
    assert made == [d for d in _expected(days, 0) if d >= cfg.start]


def test_tranche_strategy_configs_are_m106_with_only_the_offset_changed():
    base = yaml.safe_load((ROOT / "strategies/momentum/configs/m106_gap30_g25_jr_b2.yaml").read_text())
    for n in (5, 10, 15):
        path = ROOT / f"strategies/momentum/configs/m135_m106_off{n}.yaml"
        cfg = yaml.safe_load(path.read_text())
        assert cfg["params"]["schedule"].pop("decision_offset_sessions") == n
        b = {**base["params"], "schedule": {k: v for k, v in base["params"]["schedule"].items()
                                            if k != "decision_offset_sessions"}}
        assert cfg["params"] == b
        check_supported(load_strategy_config(path, ROOT).params)
