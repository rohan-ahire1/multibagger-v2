"""NSE trading calendar from the exchange's holiday list, kept as dated snapshots in the raw store.

The paper step must know at a close whether that session ends the month, before the next session exists in the data.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from mb.config.models import CalendarSource
from mb.sources.http import bootstrap, build_session


class CalendarError(RuntimeError):
    pass


def snapshot_path(root: Path, cfg: CalendarSource, day: date) -> Path:
    return root / cfg.raw_dir / f"holidays-{day.isoformat()}.json"


def fetch(cfg: CalendarSource, root: Path, today: date) -> Path:
    """Save today's holiday list once. An existing snapshot for today is kept."""
    out = snapshot_path(root, cfg, today)
    if out.exists():
        return out
    session = build_session()
    bootstrap(session, cfg.timeout_s)
    resp = session.get(cfg.url, timeout=cfg.timeout_s, headers={"Accept": "application/json"})
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict) or not isinstance(payload.get(cfg.segment), list):
        raise CalendarError(f"holiday list has no '{cfg.segment}' segment")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.rename(out)
    return out


def load(cfg: CalendarSource, root: Path) -> set[date]:
    """Holidays from the newest snapshot."""
    snaps = sorted((root / cfg.raw_dir).glob("holidays-*.json"))
    if not snaps:
        raise CalendarError(f"no holiday snapshot under {root / cfg.raw_dir}")
    rows = json.loads(snaps[-1].read_text())[cfg.segment]
    return {datetime.strptime(r["tradingDate"], "%d-%b-%Y").date() for r in rows}


def is_trading_day(d: date, holidays: set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def _covered(d: date, holidays: set[date]) -> None:
    if not any(h.year == d.year for h in holidays):
        raise CalendarError(f"the holiday list does not cover {d.year}")


def is_month_end(d: date, holidays: set[date]) -> bool:
    """True if no trading day follows `d` in its month."""
    _covered(d, holidays)
    nxt = d + timedelta(days=1)
    while nxt.month == d.month:
        if is_trading_day(nxt, holidays):
            return False
        nxt += timedelta(days=1)
    return True


def sessions_left_in_month(d: date, holidays: set[date]) -> int:
    """Trading days after `d` in its month (M135: a book with decision offset N decides when this equals N)."""
    _covered(d, holidays)
    n, nxt = 0, d + timedelta(days=1)
    while nxt.month == d.month:
        n += is_trading_day(nxt, holidays)
        nxt += timedelta(days=1)
    return n


def trading_days_between(after: date, through: date, holidays: set[date]) -> list[date]:
    """Trading days in (after, through]."""
    _covered(through, holidays)
    out, d = [], after + timedelta(days=1)
    while d <= through:
        if is_trading_day(d, holidays):
            out.append(d)
        d += timedelta(days=1)
    return out
