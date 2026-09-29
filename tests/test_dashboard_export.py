"""The dashboard exporter on small synthetic run records, datasets and paper books."""
from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from mb.config.loader import ConfigError
from mb.dashboard import config as dash_config
from mb.dashboard import export
from mb.live.paper import Book, Position, write_json

REPO = Path(__file__).resolve().parents[1]
REF = "toy@v1"
DAYS = [d for d in (date(2020, 1, 1) + timedelta(days=i) for i in range(60)) if d.weekday() < 5]


def write_run(runs: Path, run_id: str, trades: pl.DataFrame, *, final: bool = False, dataset: str = REF) -> None:
    folder = runs / run_id
    folder.mkdir(parents=True)
    eq = [1_000_000 + 1_000 * i for i in range(len(DAYS))]
    pl.DataFrame({"date": DAYS, "equity": eq, "cash": eq, "invested_value": [0.0] * len(DAYS),
                  "open_positions": [0] * len(DAYS)}).write_parquet(folder / "equity.parquet")
    trades.write_parquet(folder / "trades.parquet")
    (folder / "manifest.json").write_text(json.dumps({
        "config_file": str(runs.parent / "strategies" / "x" / "cfg.yaml"), "config_hash": "ab" * 32, "dataset": dataset,
        "final": final, "period": ["2020-01-01", "2020-03-31"], "question": None, "run_id": run_id, "strategy": "x/cfg"}))
    (folder / "metrics.json").write_text(json.dumps({"strategy": {"cagr_pct": 1.0}, "folds": {}, "baselines": {}}))


MOMENTUM = pl.DataFrame({
    "symbol": ["AAA", "BBB"], "entry_date": [DAYS[3], DAYS[5]], "exit_date": [DAYS[20], DAYS[-1]],
    "bought": [1000.0, 2000.0], "sold": [1100.0, 2100.0], "pnl": [100.0, 100.0], "return_pct": [10.0, 5.0],
    "r_multiple": [None, None], "holding_days": [17, 30], "status": ["rebalanced_out", "open"]})
SEPA = pl.DataFrame({
    "symbol": ["AAA"], "signal_date": [DAYS[2]], "entry_date": [DAYS[3]], "entry_price": [10.0], "stop": [9.0],
    "exit_date": [DAYS[9]], "exit_price": [12.0], "shares": [100.0], "return_pct": [20.0], "r_multiple": [2.0],
    "pnl": [200.0], "status": ["stopped"], "holding_days": [6]})


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, Path]:
    """(repo root, data root): baselines and the sector map in the repo root; runs, dataset and TRI in the data root."""
    root, data = tmp_path / "repo", tmp_path / "data"
    (root / "configs" / "reference").mkdir(parents=True)
    shutil.copy(REPO / "configs" / "baselines.yaml", root / "configs" / "baselines.yaml")
    (root / "configs" / "reference" / "sector_map.csv").write_text("Symbol,Industry,Source\nAAA,Metals,x\nBBB,Banks,x\n")
    tri = data / "data" / "raw" / "benchmarks" / "nifty500_tri_2010-01-04_2026-03-17.csv"
    tri.parent.mkdir(parents=True)
    pl.DataFrame({"date": DAYS[::2], "tri": [1000.0 + i for i in range(len(DAYS[::2]))]}).write_csv(tri)
    panel = pl.DataFrame([
        {"date": d, "symbol": s, "security_id": sid, "adj_open": 10.0 + i + k, "adj_close": 10.5 + i + k}
        for i, d in enumerate(DAYS) for k, (s, sid) in enumerate((("AAA", "isin:INE001"), ("BBB", "isin:INF002")))])
    ds = data / "data" / "datasets" / "toy" / "v1"
    ds.mkdir(parents=True)
    panel.write_parquet(ds / "panel.parquet")
    write_run(data / "runs", "run-mom", MOMENTUM)
    write_run(data / "runs", "run-sepa", SEPA, final=True)
    (data / "runs" / "pins.json").write_text(json.dumps({"sepa/pin": "run-sepa"}))
    return root, data


def toy_config(**over: object) -> dash_config.DashboardConfig:
    raw = {"name": "toy", "output": "out/bundle.json", "runs_dir": "runs", "sector_map": "configs/reference/sector_map.csv",
           "groups": ["G"], "bundle": {"equity_decimals": 0, "price_decimals": 2, "chart_weeks_before": 1, "chart_weeks_after": 1},
           "ui": {"page_size": 15, "return_buckets": [-10, 0, 10], "range_years": [3, 1], "heat_full_pct": 12},
           "paper": {"preview_dataset": REF, "next_in_line": 3, "recent_fills": 5, "books": []},
           "runs": [{"run": "run-mom", "label": "Momentum", "group": "G"}, {"pin": "sepa/pin", "label": "SEPA", "group": "G", "tag": "Locked"}]}
    raw.update(over)
    return dash_config.DashboardConfig.model_validate(raw)


def test_bundle_shape(world):
    root, data = world
    b = export.build(toy_config(), root, data, "configs/dashboard/toy.yaml")
    assert b["config"] == "configs/dashboard/toy.yaml"
    assert b["cal"][0] == DAYS[0].isoformat() and len(b["cal"]) == len(DAYS)
    assert b["data_to"] == DAYS[-1].isoformat()
    mom, sepa = b["runs"]
    assert (mom["id"], sepa["id"]) == ("run-mom", "run-sepa")
    assert len(mom["equity"]) == len(b["cal"]) == len(b["tri"])
    assert mom["equity"][0] == 1_000_000 and mom["tag"] == "Dev" and sepa["tag"] == "Locked"
    assert mom["config"] == "strategies/x/cfg.yaml"          # recorded absolute path made repo-relative
    assert b["tri"][1] is None and b["tri"][0] == 1000.0        # TRI only on some sessions
    assert b["weeks"][-1] == len(b["cal"]) - 1
    assert b["ui"]["range_years"] == [3, 1] and b["adoption_metric"] == "calmar"
    assert (mom["px_source"], sepa["px_source"]) == ("dataset", "recorded")


def test_trade_prices_recorded_or_from_dataset(world):
    root, data = world
    b = export.build(toy_config(), root, data, "c.yaml")
    sym = {s: i for i, s in enumerate(b["symbols"])}
    mom, sepa = b["runs"]
    # momentum: the dataset's adjusted open on entry and exit; an open trade exits at the adjusted close
    assert mom["trades"][0][8] == 10.0 + 3 and mom["trades"][0][9] == 10.0 + 20
    assert mom["trades"][1][8] == 11.0 + 5 and mom["trades"][1][9] == 11.5 + len(DAYS) - 1
    assert mom["trades"][0][0] == sym["AAA"] and mom["trades"][0][3] == 1000
    # sepa: the recorded fills, size is shares x entry price
    assert sepa["trades"][0][8:] == [10.0, 12.0] and sepa["trades"][0][3] == 1000


def test_funds_and_sectors(world):
    root, data = world
    b = export.build(toy_config(), root, data, "c.yaml")
    assert [b["symbols"][i] for i in b["funds"]] == ["BBB"]
    assert dict(zip(b["symbols"], b["sectors"])) == {"AAA": "Metals", "BBB": "Banks"}


def test_prices_are_windowed_per_dataset(world):
    root, data = world
    b = export.build(toy_config(), root, data, "c.yaml")
    segs = b["price_sets"][REF][str(b["symbols"].index("AAA"))]
    weeks_covered = sum(len(s[1]) for s in segs)
    assert 0 < weeks_covered <= len(b["weeks"])
    first, closes = segs[0]
    assert closes[0] == pytest.approx(10.5 + [i for i, d in enumerate(DAYS) if d.isocalendar()[:2] == DAYS[b["weeks"][first]].isocalendar()[:2]][-1])


def test_write_is_compact_and_atomic(world, tmp_path):
    root, data = world
    b = export.build(toy_config(), root, data, "c.yaml")
    out = tmp_path / "deep" / "bundle.json"
    size = export.write(b, out)
    assert size == len(out.read_text()) and json.loads(out.read_text())["name"] == "toy"
    assert not out.with_suffix(".tmp").exists()


def test_unknown_pin_and_missing_run_and_duplicates(world):
    root, data = world
    with pytest.raises(ConfigError, match="pin 'nope'"):
        export.build(toy_config(runs=[{"pin": "nope", "label": "x", "group": "G"}]), root, data, "c.yaml")
    with pytest.raises(ConfigError, match="not found"):
        export.build(toy_config(runs=[{"run": "missing", "label": "x", "group": "G"}]), root, data, "c.yaml")
    twice = [{"run": "run-mom", "label": "a", "group": "G"}, {"pin": "sepa/pin", "label": "b", "group": "G"},
             {"run": "run-sepa", "label": "c", "group": "G"}]
    with pytest.raises(ConfigError, match="listed twice"):
        export.build(toy_config(runs=twice), root, data, "c.yaml")


def test_config_rejects_bad_entries():
    with pytest.raises(ValueError, match="exactly one"):
        toy_config(runs=[{"run": "a", "pin": "b", "label": "x", "group": "G"}])
    with pytest.raises(ValueError, match="not listed"):
        toy_config(runs=[{"run": "a", "label": "x", "group": "Other"}])


def test_real_config_loads():
    cfg = dash_config.load(REPO / "configs" / "dashboard" / "research.yaml")
    assert len(cfg.runs) == len({(r.run, r.pin) for r in cfg.runs})
    assert {b.backtest_run for b in cfg.paper.books} <= {r.run for r in cfg.runs if r.run}


def test_week_ends_and_windows():
    cal = [date(2020, 1, 6) + timedelta(days=i) for i in (0, 1, 2, 7, 8, 14, 15, 16)]   # weeks: 3 sessions, 2, 3
    assert export.week_ends(cal) == [2, 4, 7]
    w = export.weekly_windows([("A", 3, 3), ("A", 6, 6), ("B", 0, 0)], [2, 4, 7], 0, 0)
    assert w["A"] == [(0, 2)] and w["B"] == [(0, 1)]   # one-week margin each side; A's two windows merge


def test_price_segments_split_on_gaps():
    weekly = pl.DataFrame({"symbol": ["A"] * 4, "week": [0, 1, 5, 6], "close": [1.0, 2.0, 3.0, 4.0]})
    got = export.price_segments(weekly, {"A": [(0, 6)]}, {"A": 7}, 1)
    assert got == {"7": [[0, [1.0, 2.0]], [5, [3.0, 4.0]]]}


def test_schedule_text(tmp_path):
    t = tmp_path / "x.timer"
    t.write_text("[Timer]\nOnCalendar=Mon..Fri 19:45 Asia/Kolkata\nOnCalendar=Mon..Fri 23:15 Asia/Kolkata\n")
    assert export.schedule_text(t) == "Mon–Fri 19:45 · 23:15 IST"
    t.write_text("[Timer]\n")
    with pytest.raises(ConfigError):
        export.schedule_text(t)


def test_first_month_end_skips_holidays():
    holidays = {date(2026, 9, 30), date(2026, 10, 1)}
    assert export.first_month_end(date(2026, 9, 28), holidays) == date(2026, 9, 29)
    assert export.first_month_end(date(2026, 9, 30), holidays | {date(2026, 10, 30), date(2026, 10, 31)}) == date(2026, 10, 29)


def test_live_state_none_until_the_book_has_run(tmp_path):
    cfg = SimpleNamespace(name="b", initial_capital=1_000_000.0)
    assert export.live_state(tmp_path, cfg, 5) is None
    write_json(tmp_path / "data" / "paper" / "b" / "book.json", Book(None, 1_000_000.0).to_json())
    assert export.live_state(tmp_path, cfg, 5) is None


def test_live_state_reads_book_and_days(tmp_path):
    cfg = SimpleNamespace(name="b", initial_capital=1_000_000.0)
    pos = Position(shares=100, entry=date(2026, 10, 1), paid=50_000.0, received=0.0, last_close=550.0, last_date=date(2026, 10, 2))
    book = Book(date(2026, 10, 2), 945_000.0, {"AAA": pos}, {"decided": "2026-09-30", "orders": [{"symbol": "BBB", "side": "buy", "shares": 1}]})
    base = tmp_path / "data" / "paper" / "b"
    write_json(base / "book.json", book.to_json())
    for s, eq in (("2026-10-01", 990_000.0), ("2026-10-02", 1_000_000.0)):
        write_json(base / "days" / f"{s}.json", {"session": s, "equity": eq, "decision": {"picks": ["AAA"]} if s == "2026-10-01" else None,
                                                  "fills": [{"symbol": "AAA", "side": "buy", "shares": 100, "price": 500.0, "cash_flow": -50_000.0}] if s == "2026-10-01" else []})
    live = export.live_state(tmp_path, cfg, 5)
    assert live["as_of"] == "2026-10-02" and live["equity"] == 1_000_000.0 and live["return_pct"] == 0.0
    assert live["positions"][0] == {"symbol": "AAA", "shares": 100, "entry": "2026-10-01", "close": 550.0, "value": 55000,
                                    "weight_pct": 5.5, "gain_pct": 10.0}
    assert live["pending"] == 1 and live["sessions"] == 2 and live["decisions"] == 1 and live["last_decision"] == "2026-10-01"
    assert live["curve"][-1] == ["2026-10-02", 1_000_000.0]
    assert live["fills"] == [{"session": "2026-10-01", "symbol": "AAA", "side": "buy", "shares": 100, "price": 500.0, "cash_flow": -50_000.0}]
