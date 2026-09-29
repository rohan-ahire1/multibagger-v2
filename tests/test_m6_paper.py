"""M6: trading calendar, paper book (fills, corporate actions, jump refusal), replay against the backtest, daily datasets."""
from __future__ import annotations

import json
import math
import shutil
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
import yaml
from data_fixture import write_data_config, write_raw
from test_m3_sepa import _cfg, _market
from test_m5_momentum import _params

from mb.config.loader import ConfigError, Resolved, load_data_config, load_paper_config
from mb.config.models import CalendarSource, PaperAlerts, PaperConfig, Period, StrategyConfig
from mb.live import calendar
from mb.live.daily import ensure_dataset, prune, versions
from mb.live.paper import Blocked, Book, DataView, Position, Store, advance, history_rows, load_view
from mb.live.replay import replay
from mb.strategy.momentum.targets import targets

ROOT = Path(__file__).resolve().parents[1]
CAL = CalendarSource(url="http://x", segment="CM", raw_dir="data/raw/nse_holidays", timeout_s=1.0)


def _paper_cfg(start: date, **over) -> PaperConfig:
    d = dict(name="t", strategy_config="s.yaml", strategy_config_hash="h", data_config="d.yaml", start=start,
             initial_capital=100000.0, keep_datasets=2, max_missing_sessions=1, replay_max_equity_gap_pct=2.0,
             calendar=CAL, alerts=PaperAlerts(ntfy_url="http://n", topic_env="MB_TEST_TOPIC_UNSET", heartbeat_weekday=4))
    return PaperConfig(**(d | over))


def _strat(cost: bool = True, **params) -> Resolved:
    s = StrategyConfig(name="momentum", version="t", dataset="x@1", market="m",
                       period=Period(start=date(2020, 1, 1), end=date(2020, 1, 2)), params={})
    return Resolved(s, _params(**params), _market(cost), _cfg("x"), Path("s.yaml"))


def _days(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _panel(days: list[date], drifts: dict[str, float], factor: dict[tuple[str, date], float] | None = None) -> pl.DataFrame:
    """Raw prices with a small wiggle; adj_* = raw * adj_factor (1 unless given)."""
    rows = []
    for sym, drift in drifts.items():
        for i, d in enumerate(days):
            px = round(100.0 * (1 + drift) ** i * (1 + 0.01 * math.sin(i + len(sym))), 2)
            f = (factor or {}).get((sym, d), 1.0)
            rows.append((d, sym, f"isin:INE{sym}", "EQ", px, px, 1e9, px * f, px * f, f))
    return pl.DataFrame(rows, schema=["date", "symbol", "security_id", "series", "open", "close", "turnover", "adj_open",
                                      "adj_close", "adj_factor"], orient="row")


def _view(panel: pl.DataFrame, share_mult: dict | None = None, jumps: list[tuple[str, date]] | None = None) -> DataView:
    j = pl.DataFrame([(s, d, 2.0) for s, d in (jumps or [])], schema={"symbol": pl.String, "date": pl.Date, "ratio": pl.Float64},
                     orient="row")
    return DataView("t@1", "sha", panel, share_mult or {}, j)


# --- calendar -------------------------------------------------------------------------------------------------------

def test_month_end_skips_trailing_holidays_and_needs_the_year_covered():
    hol = {date(2026, 10, 30), date(2026, 10, 2)}  # Fri 30 Oct is a holiday, so Thu 29 Oct ends the month
    assert calendar.is_month_end(date(2026, 10, 29), hol)
    assert not calendar.is_month_end(date(2026, 10, 28), hol)
    assert calendar.is_month_end(date(2026, 9, 30), hol)
    assert calendar.trading_days_between(date(2026, 9, 30), date(2026, 10, 5), hol) == [date(2026, 10, 1), date(2026, 10, 5)]
    with pytest.raises(calendar.CalendarError):
        calendar.is_month_end(date(2027, 1, 29), hol)


def test_calendar_reads_the_newest_snapshot(tmp_path):
    d = tmp_path / CAL.raw_dir
    d.mkdir(parents=True)
    (d / "holidays-2026-01-01.json").write_text(json.dumps({"CM": [{"tradingDate": "26-Jan-2026"}]}))
    (d / "holidays-2026-06-01.json").write_text(json.dumps({"CM": [{"tradingDate": "02-Oct-2026"}]}))
    assert calendar.load(CAL, tmp_path) == {date(2026, 10, 2)}


# --- paper book -----------------------------------------------------------------------------------------------------

def _hol(days: list[date]) -> set[date]:
    """A weekend date in every year, so the calendar covers them without removing a session."""
    return {date(y, 1, 4) if date(y, 1, 4).weekday() >= 5 else date(y, 1, 5 + (5 - date(y, 1, 5).weekday()) % 7)
            for y in {d.year for d in days}}


def test_paper_book_matches_the_backtest_replay(tmp_path):
    days = _days(date(2023, 6, 1), 200)
    drifts = {"AAA": 0.004, "BBB": 0.002, "CCC": -0.001, "DDD": 0.003, "EEE": 0.0}
    view = _view(_panel(days, drifts))
    cfg, strat = _paper_cfg(date(2023, 8, 1)), _strat(True, portfolio={"top_n": 2, "hold_rank_max": 2})
    store = Store(tmp_path, cfg.name)
    book, recs, notes = advance(Book(None, cfg.initial_capital), cfg, strat, view, _hol(days), store)
    assert recs and book.as_of == days[-1] and all("scaled" in n for n in notes)
    assert all(isinstance(p.shares, int) and p.shares > 0 for p in book.positions.values())
    assert book.cash >= 0
    decisions = [r for r in recs if r["decision"]]
    assert len(decisions) >= 5 and all(len(r["decision"]["picks"]) == 2 for r in decisions)
    rep = replay(cfg, strat, view, store.days())
    assert rep["decision_mismatches"] == [] and rep["ok"]
    assert abs(rep["equity_gap_pct"]) < 0.5
    # Re-running commits nothing new.
    again, recs2, _ = advance(store.load_book(cfg), cfg, strat, view, _hol(days), store)
    assert recs2 == [] and again.to_json() == book.to_json()


def test_split_multiplies_shares_and_pending_orders_and_a_dividend_is_cash():
    days = _days(date(2024, 3, 4), 3)
    ex = days[1]
    factor = {("AAA", days[0]): 0.5, ("BBB", days[0]): 0.98}  # 2-for-1 split on AAA, 2% dividend on BBB
    panel = _panel(days, {"AAA": 0.0, "BBB": 0.0}, factor)
    view = _view(panel, {(ex, "AAA"): 0.5})
    pc = {s: panel.filter((pl.col("symbol") == s) & (pl.col("date") == days[0]))["close"][0] for s in ("AAA", "BBB")}
    book = Book(days[0], 10000.0, {"AAA": Position(11, days[0], 1000.0, 0.0, pc["AAA"], days[0]),
                                   "BBB": Position(10, days[0], 1000.0, 0.0, pc["BBB"], days[0])},
                {"decided": days[0].isoformat(), "orders": [{"symbol": "AAA", "side": "sell", "shares": 5}]})
    cfg, strat = _paper_cfg(days[0]), _strat(False)
    book, recs, _ = advance(book, cfg, strat, view, _hol(days), None)
    kinds = {(c["symbol"], c["kind"]) for c in recs[0]["corporate_actions"]}
    assert kinds == {("AAA", "share_event"), ("BBB", "cash_adjustment")}
    assert book.positions["AAA"].shares == 22 - 10  # 11 -> 22 on the split; the order for 5 became 10
    assert recs[0]["fills"][0]["shares"] == 10
    div = next(c for c in recs[0]["corporate_actions"] if c["kind"] == "cash_adjustment")
    assert div["per_share"] == pytest.approx(0.02 * pc["BBB"]) and div["cash"] == pytest.approx(10 * 0.02 * pc["BBB"])


def test_buys_scale_down_in_whole_shares_when_cash_is_short():
    days = _days(date(2024, 3, 4), 2)
    view = _view(_panel(days, {"AAA": 0.0, "BBB": 0.0}))
    book = Book(days[0], 1000.0, {}, {"decided": days[0].isoformat(), "orders": [
        {"symbol": "AAA", "side": "buy", "shares": 10}, {"symbol": "BBB", "side": "buy", "shares": 10}]})
    book, recs, notes = advance(book, _paper_cfg(days[0]), _strat(True), view, _hol(days), None)
    assert {p.shares for p in book.positions.values()} <= {4, 5} and book.cash >= 0
    assert any("scaled" in n for n in notes)


def test_an_unexplained_jump_on_a_held_name_blocks_the_session_and_commits_nothing(tmp_path):
    days = _days(date(2024, 3, 4), 3)
    view = _view(_panel(days, {"AAA": 0.0}), jumps=[("AAA", days[2])])
    cfg = _paper_cfg(days[0])
    store = Store(tmp_path, cfg.name)
    start = Book(days[0], 0.0, {"AAA": Position(10, days[0], 1000.0, 0.0, 100.0, days[0])})
    store.save_book(start)
    with pytest.raises(Blocked) as e:
        advance(store.load_book(cfg), cfg, _strat(False), view, _hol(days), store)
    assert e.value.session == days[2] and "AAA" in e.value.reasons[0]
    assert store.load_book(cfg).as_of == days[1]  # the clean session before it was committed


# --- config and daily datasets --------------------------------------------------------------------------------------

def test_paper_config_refuses_a_changed_strategy_config(tmp_path):
    for sub in ("configs/market", "strategies/momentum/configs", "configs/paper"):
        (tmp_path / sub).mkdir(parents=True)
    shutil.copy(ROOT / "configs/market/nse_cash.yaml", tmp_path / "configs/market")
    shutil.copy(ROOT / "configs/baselines.yaml", tmp_path / "configs")
    src = ROOT / "strategies/momentum/configs/voladj_final.yaml"
    shutil.copy(src, tmp_path / "strategies/momentum/configs")
    shutil.copy(ROOT / "configs/paper/momentum_voladj.yaml", tmp_path / "configs/paper")
    paper = tmp_path / "configs/paper/momentum_voladj.yaml"
    cfg, _ = load_paper_config(paper, tmp_path)
    assert cfg.start == date(2026, 9, 30)
    edited = yaml.safe_load(src.read_text())
    edited["params"]["portfolio"]["top_n"] = 20
    (tmp_path / "strategies/momentum/configs/voladj_final.yaml").write_text(yaml.safe_dump(edited))
    with pytest.raises(ConfigError, match="pinned"):
        load_paper_config(paper, tmp_path)


def test_daily_dataset_is_rebuilt_only_when_inputs_change_and_old_versions_are_pruned(tmp_path):
    write_raw(tmp_path)
    dcfg, dhash = load_data_config(write_data_config(tmp_path))
    ref, built = ensure_dataset(dcfg, dhash, tmp_path)
    assert built and ref == "fixture@2023-03-24"
    assert ensure_dataset(dcfg, dhash, tmp_path) == (ref, False)
    (tmp_path / "configs/data/verified_moves.csv").write_text("symbol,date,reason,source\r\n")  # new bytes, same content
    ref2, built2 = ensure_dataset(dcfg, dhash, tmp_path)
    assert built2 and ref2 == "fixture@2023-03-24.01"
    assert prune(tmp_path, "fixture", 1) == ["2023-03-24"] and versions(tmp_path, "fixture") == ["2023-03-24.01"]


def test_the_view_keeps_only_the_history_the_strategy_reads(tmp_path):
    write_raw(tmp_path)
    dcfg, dhash = load_data_config(write_data_config(tmp_path))
    ref, _ = ensure_dataset(dcfg, dhash, tmp_path)
    p = _params(ranking={"lookback_sessions": 10, "skip_sessions": 2}, universe={"adv_window_sessions": 5})
    full = pl.read_parquet(tmp_path / "data/datasets/fixture/2023-03-24/panel.parquet")
    start = sorted(full["date"].unique())[30]
    view = load_view(tmp_path, ref, start, p)
    assert view.panel.filter(pl.col("date") < start).group_by("symbol").len()["len"].max() == history_rows(p)
    end = full["date"].max()
    assert targets(view.panel, p, start, end) == targets(full, p, start, end)
