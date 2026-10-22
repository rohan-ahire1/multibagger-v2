"""The daily paper job: update data, build a dataset if anything changed, advance the book, replay, alert.

Safe to run more than once a day: downloads skip what exists, the dataset is rebuilt only when its inputs change, and
the book only processes sessions it has not committed.
"""
from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from mb.config.loader import load_data_config, load_paper_config
from mb.config.models import DataConfig, DataConfigM40, PaperConfig
from mb.data import build, datasets
from mb.live import calendar
from mb.live.alerts import Alerter
from mb.live.paper import Blocked, Store, advance, load_view, off_series, write_json
from mb.live.replay import replay, report
from mb.sources import nse_bhavcopy, nse_corporate_actions, nse_delivery


def versions(root: Path, name: str) -> list[str]:
    base = datasets.datasets_dir(root) / name
    return sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")) if base.is_dir() else []


def latest_ref(root: Path, name: str) -> str | None:
    v = versions(root, name)
    return f"{name}@{v[-1]}" if v else None


def ensure_dataset(dcfg: DataConfig, dhash: str, root: Path) -> tuple[str, bool]:
    """The newest version if its inputs and config are unchanged, else a new build labelled by its last session."""
    zips = nse_bhavcopy.build_zips(root / dcfg.bhavcopy.raw_dir, dcfg.bhavcopy)
    inputs = build._inputs(dcfg, root, zips)
    have = versions(root, dcfg.name)
    if have:
        m = datasets.read_manifest(datasets.datasets_dir(root) / dcfg.name / have[-1])
        if m["inputs"] == inputs and m["config_hash"] == dhash:
            return f"{dcfg.name}@{have[-1]}", False
    base = nse_bhavcopy.zip_date(zips[-1]).isoformat()
    label, n = base, 0
    while label in have:
        n += 1
        label = f"{base}.{n:02d}"
    build.build(dcfg, dhash, root, label)
    return f"{dcfg.name}@{label}", True


def prune(root: Path, name: str, keep: int) -> list[str]:
    old = versions(root, name)[:-keep]
    for v in old:
        shutil.rmtree(datasets.datasets_dir(root) / name / v)
    return old


def fetch_delivery(dcfg: DataConfigM40, root: Path) -> dict[str, list[str]]:
    """M43: delivery files for the build's bhavcopy sessions that have none. NSE can publish one after the bhavcopy, so
    a session still missing is tried again on every run."""
    raw = root / dcfg.delivery.raw_dir
    want = [nse_bhavcopy.zip_date(z) for z in nse_bhavcopy.build_zips(root / dcfg.bhavcopy.raw_dir, dcfg.bhavcopy)]
    missing = [d for d in want if not nse_delivery.file_path(raw, d).exists()]
    got = nse_delivery.fetch(dcfg.delivery, raw, missing) if missing else {"downloaded": [], "missing": []}
    return {k: [d.isoformat() for d in v] for k, v in got.items()}


def _update_raw(cfg: PaperConfig, dcfg: DataConfig, root: Path, today: date, problems: list[str], log: dict) -> None:
    try:
        calendar.fetch(cfg.calendar, root, today)
    except Exception as e:  # noqa: BLE001 - an older snapshot still serves; stale coverage fails later
        problems.append(f"holiday list fetch failed: {e}")
    raw_dir = root / dcfg.bhavcopy.raw_dir
    last = nse_bhavcopy.zip_date(nse_bhavcopy.list_zips(raw_dir)[-1])
    try:
        got = nse_bhavcopy.fetch(dcfg.bhavcopy, raw_dir, last, today)
        log["bhavcopy"] = {k: [d.isoformat() for d in v] for k, v in got.items()}
    except Exception as e:  # noqa: BLE001
        problems.append(f"bhavcopy fetch failed: {e}")
    if isinstance(dcfg, DataConfigM40):
        try:
            log["delivery"] = fetch_delivery(dcfg, root)
        except Exception as e:  # noqa: BLE001
            problems.append(f"delivery fetch failed: {e}")
    years = sorted({today.year, today.year - 1 if today.month == 1 else today.year})
    try:
        merged, failed = nse_corporate_actions.fetch(dcfg.corporate_actions, root, years[0], years[-1])
        log["corporate_actions"] = {"rows": merged.height, "failed_windows": [str(d) for d in failed]}
        if failed:
            problems.append(f"corporate-action windows {', '.join(map(str, failed))} failed to download")
    except Exception as e:  # noqa: BLE001
        problems.append(f"corporate-action fetch failed: {e}")


def run(cfg_path: Path, root: Path, today: date, fetch: bool = True, alerter: Alerter | None = None) -> int:
    """0 when everything is clean, 1 when something needs a person (every problem was alerted)."""
    cfg, strat = load_paper_config(cfg_path, root)
    dcfg, dhash = load_data_config(root / cfg.data_config)
    store = Store(root, cfg.name)
    alerter = alerter or Alerter(cfg.alerts)
    problems: list[str] = []
    log: dict[str, Any] = {"started_at": datetime.now(UTC).isoformat(), "today": today.isoformat(), "fetch": fetch}

    if fetch:
        _update_raw(cfg, dcfg, root, today, problems, log)
    try:
        ref, built = ensure_dataset(dcfg, dhash, root) if fetch else (latest_ref(root, dcfg.name), False)
    except build.CheckFailure as e:
        problems.append(f"dataset build refused: {e}")
        ref, built = None, False
    log["dataset"], log["built"] = ref, built
    if ref is None:
        return _finish(cfg, store, alerter, problems or ["no daily dataset"], log, today)
    log["pruned"] = prune(root, dcfg.name, cfg.keep_datasets)

    holidays = calendar.load(cfg.calendar, root)
    last_session = date.fromisoformat(datasets.read_manifest(datasets.dataset_path(root, ref))["date_max"])
    missing = calendar.trading_days_between(last_session, today, holidays)
    log["last_session"], log["missing_sessions"] = last_session.isoformat(), [d.isoformat() for d in missing]
    if len(missing) > cfg.max_missing_sessions:
        problems.append(f"stale data: newest session {last_session}; missing {', '.join(map(str, missing))}")

    view = load_view(root, ref, cfg.start, strat.params)
    book = store.load_book(cfg)
    try:
        book, recs, notes = advance(book, cfg, strat, view, holidays, store)
    except Blocked as b:
        recs, notes = [], []
        problems.append(f"book stopped before {b.session}: " + "; ".join(b.reasons))
        book = store.load_book(cfg)
    log["sessions"] = [r["session"] for r in recs]
    log["notes"] = notes
    for r in recs:
        if r["decision"] is not None:
            _decision_push(cfg, r, alerter)

    log["off_series"] = off_series(book, view, strat.params.universe.allowed_series)

    rep = replay(cfg, strat, view, store.days())
    if rep is not None:
        store.save_text("replays", f"{rep['as_of']}.md", report(rep))
        log["replay"] = rep
        if not rep["ok"]:
            problems.append(f"replay mismatch through {rep['as_of']}: gap {rep['equity_gap_pct']:+.2f}%, "
                            f"{len(rep['decision_mismatches'])} decision(s) differ")
    if not problems and today.weekday() == cfg.alerts.heartbeat_weekday and not (store.dir / "daily" / f"heartbeat-{today}").exists():
        _heartbeat(cfg, book, rep, last_session, alerter, log["off_series"])
        store.save_text("daily", f"heartbeat-{today}", "")
    return _finish(cfg, store, alerter, problems, log, today)


def _finish(cfg: PaperConfig, store: Store, alerter: Alerter, problems: list[str], log: dict, today: date) -> int:
    log["problems"] = problems
    log["finished_at"] = datetime.now(UTC).isoformat()
    write_json(store.dir / "daily" / f"{today}-{datetime.now(UTC):%H%M%S}.json", log)
    if problems:
        alerter.send(f"{cfg.name}: needs attention", "\n".join(f"- {p}" for p in problems), "high", ("warning",))
        return 1
    return 0


def _decision_push(cfg: PaperConfig, rec: dict, alerter: Alerter) -> None:
    d = rec["decision"]
    buys = [o for o in d["orders"] if o["side"] == "buy"]
    sells = [o for o in d["orders"] if o["side"] == "sell"]
    body = (f"Decided at the {rec['session']} close, fills at the next open. Equity Rs {d['equity_at_close']:,.0f}.\n"
            f"Buy {len(buys)}: {', '.join(o['symbol'] for o in buys) or '-'}\n"
            f"Sell {len(sells)}: {', '.join(o['symbol'] for o in sells) or '-'}")
    alerter.send(f"{cfg.name}: orders for the next open", body, "default", ("chart_with_upwards_trend",))


def _heartbeat(cfg: PaperConfig, book: Any, rep: dict | None, last_session: date, alerter: Alerter,
               off: list[str]) -> None:
    ret = (book.equity() / cfg.initial_capital - 1) * 100
    gap = f", replay gap {rep['equity_gap_pct']:+.2f}%" if rep else ""
    body = (f"Data through {last_session}. Book as of {book.as_of}: equity Rs {book.equity():,.0f} ({ret:+.2f}%), "
            f"{len(book.positions)} positions{gap}.")
    if off:
        body += "\nHeld outside the usual series (trade-to-trade: delivery only): " + "; ".join(off)
    alerter.send(f"{cfg.name}: weekly ok", body, "low", ("white_check_mark",))


def status(cfg_path: Path, root: Path) -> str:
    cfg, _ = load_paper_config(cfg_path, root)
    store = Store(root, cfg.name)
    book = store.load_book(cfg)
    days = store.days()
    decisions = [d for d in days if d["decision"]]
    lines = [f"{cfg.name}: book as of {book.as_of or 'not started'} (start {cfg.start})",
             f"equity {book.equity():,.2f}  cash {book.cash:,.2f}  return {(book.equity() / cfg.initial_capital - 1) * 100:+.2f}%",
             f"positions {len(book.positions)}  decisions {len(decisions)}"]
    if book.pending:
        lines.append(f"pending orders from {book.pending['decided']}: {len(book.pending['orders'])}")
    logs = sorted((store.dir / "daily").glob("*.json"))
    off = json.loads(logs[-1].read_text()).get("off_series") if logs else None
    if off:
        lines.append("held outside the usual series (trade-to-trade: delivery only): " + "; ".join(off))
    reps = sorted((store.dir / "replays").glob("*.md"))
    if reps:
        lines.append(reps[-1].read_text().strip())
    return "\n".join(lines)

