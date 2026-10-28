"""M147 shadow book: new sessions are recorded once; a recorded session that moves is alerted and kept."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl

from mb.config.models import CalendarSource, PaperAlerts, ShadowConfig
from mb.live import shadow


class _Alerts:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, title, body, priority="default", tags=()):
        self.sent.append((title, body))
        return True


def _cfg() -> ShadowConfig:
    return ShadowConfig(name="t", strategy_config="s.yaml", strategy_config_hash="h", data_config="d.yaml",
                        start=date(2026, 10, 1), max_missing_sessions=1, max_restated_equity_pct=0.5,
                        calendar=CalendarSource(url="u", segment="CM", raw_dir="r", timeout_s=1),
                        alerts=PaperAlerts(ntfy_url="n", topic_env="X", heartbeat_weekday=4))


def _wire(monkeypatch, curve: list[tuple[date, float]], last: date) -> None:
    eq = pl.DataFrame({"date": [d for d, _ in curve], "equity": [e for _, e in curve],
                       "invested_value": [0.0] * len(curve)})
    trades = pl.DataFrame(schema={"symbol": pl.String, "entry_date": pl.Date, "exit_date": pl.Date,
                                  "status": pl.String, "sleeve": pl.String, "return_pct": pl.Float64})
    monkeypatch.setattr(shadow, "load_shadow_config", lambda p, r: (_cfg(), object()))
    monkeypatch.setattr(shadow, "load_data_config", lambda p: (type("D", (), {"name": "nse_daily"})(), "x"))
    monkeypatch.setattr(shadow, "latest_ref", lambda r, n: "nse_daily@v")
    monkeypatch.setattr(shadow.datasets, "dataset_path", lambda r, ref: Path("."))
    monkeypatch.setattr(shadow.datasets, "read_manifest", lambda p: {"date_max": last.isoformat()})
    monkeypatch.setattr(shadow.calendar, "load", lambda c, r: set())
    monkeypatch.setattr(shadow.calendar, "trading_days_between", lambda a, b, h: [])
    monkeypatch.setattr(shadow.calendar, "is_month_end", lambda d, h: False)
    monkeypatch.setattr(shadow, "simulate", lambda *a: (eq, trades, {"s": eq}, []))


def test_records_new_sessions_once_and_flags_restatements(tmp_path, monkeypatch):
    d1, d2, d3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)
    _wire(monkeypatch, [(d1, 100.0), (d2, 101.0)], d2)
    a = _Alerts()
    assert shadow.run(Path("c.yaml"), tmp_path, date(2026, 10, 2), a) == 0
    rec = json.loads((tmp_path / "data/paper/t/sessions.json").read_text())
    assert [k for k in rec] == ["2026-10-01", "2026-10-02"] and rec["2026-10-02"]["equity"] == 101.0

    # A rebuilt dataset moves 2026-10-02 by 2%: alerted, the recorded value kept, the new session added.
    _wire(monkeypatch, [(d1, 100.0), (d2, 103.0), (d3, 104.0)], d3)
    assert shadow.run(Path("c.yaml"), tmp_path, date(2026, 10, 5), a) == 1
    rec = json.loads((tmp_path / "data/paper/t/sessions.json").read_text())
    assert rec["2026-10-02"]["equity"] == 101.0 and rec["2026-10-05"]["equity"] == 104.0
    assert any("2026-10-02" in body for title, body in a.sent if "needs attention" in title)


def test_waits_before_start(tmp_path, monkeypatch):
    _wire(monkeypatch, [], date(2026, 9, 30))
    assert shadow.run(Path("c.yaml"), tmp_path, date(2026, 9, 30), _Alerts()) == 0
    assert not (tmp_path / "data/paper/t/sessions.json").exists()
