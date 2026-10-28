"""Build the dashboard bundle: run records, the datasets they ran on, and the paper books, as one compact JSON file.

Shapes (all dates ISO strings, all indexes into `cal` unless noted):
  cal      every session from the first run date on; equity, TRI and positions arrays are aligned to it, null where absent
  weeks    the last cal index of each ISO week; trade-chart prices are weekly, one value per week
  symbols  every traded or previewed symbol; runs and prices refer to symbols by index
  runs[].trades  [symbol, entry, exit, size_inr, pnl_inr, return_pct, hold_days, status, entry_px, exit_px]
  price_sets     per dataset ref: {symbol index: [[first week, [weekly adj close, ...]], ...]}, windows around trades only
Momentum runs record no prices, so their entry and exit prices are the dataset's adjusted open on the fill dates
(`px_source` says which). SEPA runs keep the fills they recorded.
"""
from __future__ import annotations

import json
from bisect import bisect_left
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from mb.config.loader import ConfigError, load_baselines, load_paper_config, load_strategy_config
from mb.dashboard.config import DashboardConfig, PaperBook, RunEntry, ShadowBook
from mb.data import datasets
from mb.live import calendar
from mb.live.paper import Store, load_view

TRADE_STATUS_OPEN = "open"


# --- run records ----------------------------------------------------------------------------------------------------

def resolve_run(entry: RunEntry, runs_dir: Path) -> str:
    if entry.run is not None:
        return entry.run
    pins = runs_dir / "pins.json"
    if not pins.is_file():
        raise ConfigError(f"pin '{entry.pin}': {pins} not found")
    table = json.loads(pins.read_text())
    if entry.pin not in table:
        raise ConfigError(f"pin '{entry.pin}' is not in {pins}")
    return str(table[entry.pin])


class Record:
    """One run record folder, read."""

    def __init__(self, entry: RunEntry, runs_dir: Path):
        self.entry = entry
        self.id = resolve_run(entry, runs_dir)
        folder = runs_dir / self.id
        if not folder.is_dir():
            raise ConfigError(f"run {self.id} ({entry.label}): {folder} not found")
        self.manifest: dict[str, Any] = json.loads((folder / "manifest.json").read_text())
        self.metrics: dict[str, Any] = json.loads((folder / "metrics.json").read_text())
        self.equity = pl.read_parquet(folder / "equity.parquet")
        self.trades = pl.read_parquet(folder / "trades.parquet")

    @property
    def dataset(self) -> str:
        return str(self.manifest["dataset"])


def rel_path(p: str, *roots: Path) -> str:
    """A recorded absolute path, relative to the first root that holds it; unchanged otherwise."""
    path = Path(p)
    for r in roots:
        try:
            return str(path.relative_to(r.resolve()))
        except ValueError:
            continue
    return p


# --- calendar, weeks, benchmark -------------------------------------------------------------------------------------

def read_tri(root: Path, tri_file: str) -> dict[date, float]:
    df = pl.read_csv(root / tri_file, try_parse_dates=True)
    return dict(zip(df["date"].to_list(), df["tri"].to_list()))


def session_dates(root: Path, ref: str, first: date) -> list[date]:
    path = datasets.dataset_path(root, ref) / datasets.PANEL_FILE
    return pl.scan_parquet(path).filter(pl.col("date") >= first).select("date").unique().collect()["date"].to_list()


def build_calendar(records: list[Record], sessions: list[date], tri: dict[date, float]) -> list[date]:
    have: set[date] = set(sessions)
    for r in records:
        have.update(r.equity["date"].to_list())
    first = min(min(r.equity["date"]) for r in records)
    return sorted(d for d in have | {d for d in tri if d >= first} if d >= first)


def week_ends(cal: list[date]) -> list[int]:
    """The cal index of the last session of each ISO week."""
    out: list[int] = []
    prev: tuple[int, int] | None = None
    for i, d in enumerate(cal):
        key = d.isocalendar()[:2]
        if key != prev:
            out.append(i)
            prev = key
        else:
            out[-1] = i
    return out


def aligned(cal_index: dict[date, int], n: int, dates: list[date], values: list[Any], ndigits: int | None) -> list[Any]:
    out: list[Any] = [None] * n
    for d, v in zip(dates, values):
        if v is not None and d in cal_index:
            out[cal_index[d]] = round(v, ndigits) if ndigits is not None else v
    return out


# --- trades and prices ----------------------------------------------------------------------------------------------

def prepare_trades(rec: Record) -> pl.DataFrame:
    """One row per trade with the columns the bundle needs; prices are null where the record has none."""
    t = rec.trades
    cols = set(t.columns)
    price_in, price_out = ("entry_price", "exit_price") if "entry_price" in cols else (None, None)
    size = pl.col("shares") * pl.col("entry_price") if "shares" in cols else pl.col("bought")
    return t.select(
        pl.col("symbol"), pl.col("entry_date"), pl.col("exit_date"), size.alias("size"), pl.col("pnl"),
        pl.col("return_pct").alias("ret"), pl.col("holding_days").alias("hold"), pl.col("status"),
        (pl.col(price_in) if price_in else pl.lit(None, dtype=pl.Float64)).alias("entry_px"),
        (pl.col(price_out) if price_out else pl.lit(None, dtype=pl.Float64)).alias("exit_px"),
    )


def dataset_prices(root: Path, ref: str, symbols: set[str], first: date) -> pl.DataFrame:
    path = datasets.dataset_path(root, ref) / datasets.PANEL_FILE
    return (pl.scan_parquet(path).filter(pl.col("symbol").is_in(sorted(symbols)) & (pl.col("date") >= first))
            .select("date", "symbol", "security_id", "adj_open", "adj_close").collect())


def fill_prices(trades: pl.DataFrame, px: pl.DataFrame) -> pl.DataFrame:
    """Fill missing entry and exit prices from the dataset: the adjusted open on the fill date, and for a trade still
    open at the end of the run the adjusted close on its last date."""
    look = px.select("symbol", "date", "adj_open", "adj_close")
    j = (trades.join(look.rename({"adj_open": "in_open"}).drop("adj_close"), left_on=["symbol", "entry_date"], right_on=["symbol", "date"], how="left")
         .join(look.rename({"adj_open": "out_open", "adj_close": "out_close"}), left_on=["symbol", "exit_date"], right_on=["symbol", "date"], how="left"))
    out_px = pl.when(pl.col("status") == TRADE_STATUS_OPEN).then(pl.col("out_close")).otherwise(pl.col("out_open"))
    return j.with_columns(
        pl.coalesce("entry_px", "in_open").alias("entry_px"), pl.coalesce("exit_px", out_px).alias("exit_px"),
    ).drop("in_open", "out_open", "out_close")


def weekly_windows(rows: list[tuple[str, int, int]], weeks: list[int], before: int, after: int) -> dict[str, list[tuple[int, int]]]:
    """Merged week windows per symbol: each trade's chart span, from `before` weeks ahead of entry to `after` after exit."""
    nw = len(weeks)
    raw: dict[str, list[tuple[int, int]]] = {}
    for sym, ei, xi in rows:
        ew, xw = bisect_left(weeks, ei), bisect_left(weeks, xi)
        raw.setdefault(sym, []).append((max(0, ew - before - 1), min(nw - 1, xw + after + 1)))
    out: dict[str, list[tuple[int, int]]] = {}
    for sym, spans in raw.items():
        merged: list[list[int]] = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        out[sym] = [(a, b) for a, b in merged]
    return out


def weekly_close(px: pl.DataFrame, cal: list[date], weeks: list[int]) -> pl.DataFrame:
    """Per symbol and week, the adjusted close of the last session the symbol traded in that week."""
    week_of = [0] * len(cal)
    for k, end in enumerate(weeks):
        lo = weeks[k - 1] + 1 if k else 0
        for i in range(lo, end + 1):
            week_of[i] = k
    wk = pl.DataFrame({"date": cal, "week": week_of}, schema={"date": pl.Date, "week": pl.Int32})
    return (px.join(wk, on="date", how="inner").sort("symbol", "date")
            .group_by("symbol", "week", maintain_order=True).agg(pl.col("adj_close").last().alias("close")))


def price_segments(weekly: pl.DataFrame, windows: dict[str, list[tuple[int, int]]], sym_index: dict[str, int],
                   ndigits: int) -> dict[str, list[list[Any]]]:
    """{symbol index: [[first week, [closes...]], ...]}: runs of consecutive weeks inside the windows."""
    out: dict[str, list[list[Any]]] = {}
    by_sym: dict[str, list[tuple[int, float]]] = {}
    for sym, wk, close in weekly.select("symbol", "week", "close").iter_rows():
        if sym in windows and close is not None:
            by_sym.setdefault(sym, []).append((wk, close))
    for sym, pts in by_sym.items():
        spans = windows[sym]
        segs: list[list[Any]] = []
        for wk, close in pts:  # pts are sorted by week
            if not any(a <= wk <= b for a, b in spans):
                continue
            if segs and segs[-1][0] + len(segs[-1][1]) == wk:
                segs[-1][1].append(round(close, ndigits))
            else:
                segs.append([wk, [round(close, ndigits)]])
        if segs:
            out[str(sym_index[sym])] = segs
    return out


# --- paper ----------------------------------------------------------------------------------------------------------

def schedule_text(timer: Path) -> str:
    """'Mon–Fri 19:45 · 23:15 IST' from the systemd timer's OnCalendar lines."""
    days, times, tz = "", [], ""
    for line in timer.read_text().splitlines():
        if line.startswith("OnCalendar="):
            parts = line.split("=", 1)[1].split()
            days, tz = parts[0].replace("..", "–"), parts[-1]
            times.append(parts[1])
    if not times:
        raise ConfigError(f"{timer}: no OnCalendar line")
    return f"{days} {' · '.join(times)}" + (" IST" if tz == "Asia/Kolkata" else f" {tz}")


def first_month_end(start: date, holidays: set[date]) -> date:
    d = start
    for _ in range(400):
        if calendar.is_trading_day(d, holidays) and calendar.is_month_end(d, holidays):
            return d
        d = date.fromordinal(d.toordinal() + 1)
    raise ConfigError(f"no month-end within 400 days of {start}")


def preview(root: Path, ref: str, cfg_params: Any, next_in_line: int) -> dict[str, Any]:
    """The target book if the month ended at the dataset's last close: the strategy's own ranking."""
    from mb.live.paper import check_supported
    from mb.strategy.momentum.targets import ranked

    check_supported(cfg_params)
    path = datasets.dataset_path(root, ref) / datasets.PANEL_FILE
    as_of = pl.scan_parquet(path).select(pl.col("date").max()).collect().item()
    view = load_view(root, ref, as_of, cfg_params)
    order = ranked(view.panel, cfg_params.universe, cfg_params.ranking, as_of, as_of)[as_of]
    n = cfg_params.portfolio.top_n
    r = cfg_params.ranking
    f = (view.panel.sort("symbol", "date").with_columns(
        (pl.col("adj_close").shift(r.skip_sessions) / pl.col("adj_close").shift(r.lookback_sessions) - 1.0).over("symbol").alias("m121"),
        (pl.col("adj_close") / pl.col("adj_close").shift(r.skip_sessions) - 1.0).over("symbol").alias("m1"))
        .filter(pl.col("date") == as_of).select("symbol", "close", "m121", "m1"))
    row = {s: (c, a, b) for s, c, a, b in f.iter_rows()}
    picks = [[s, round(row[s][0], 2), round(row[s][1] * 100, 1), round(row[s][2] * 100, 1)] for s in order[:n]]
    return {"as_of": as_of.isoformat(), "n": n, "picks": picks, "bench": order[n:n + next_in_line]}


def live_state(root: Path, cfg: Any, recent: int) -> dict[str, Any] | None:
    """The book's state from data/paper/<name>, or None while it has never run."""
    store = Store(root, cfg.name)
    if not (store.dir / "book.json").is_file():
        return None
    book = store.load_book(cfg)
    if book.as_of is None:
        return None
    days = store.days()
    equity = book.equity()
    fills = [{"session": d["session"], **f} for d in days for f in d["fills"]]
    decisions = [d for d in days if d.get("decision")]
    positions = []
    for sym, p in sorted(book.positions.items()):
        value = p.shares * p.last_close
        positions.append({"symbol": sym, "shares": p.shares, "entry": p.entry.isoformat(), "close": round(p.last_close, 2),
                          "value": round(value), "weight_pct": round(value / equity * 100, 2),
                          "gain_pct": round((value + p.received - p.paid) / p.paid * 100, 2) if p.paid else None})
    return {
        "as_of": book.as_of.isoformat(), "equity": round(equity, 2), "cash": round(book.cash, 2),
        "return_pct": round((equity / cfg.initial_capital - 1) * 100, 2), "positions": positions,
        "pending": len(book.pending["orders"]) if book.pending else 0,
        "pending_decided": book.pending["decided"] if book.pending else None,
        "sessions": len(days), "decisions": len(decisions),
        "last_decision": decisions[-1]["session"] if decisions else None,
        "curve": [[d["session"], round(d["equity"], 2)] for d in days],
        "fills": fills[-recent:],
    }


def shadow_state(root: Path, b: ShadowBook) -> dict[str, Any] | None:
    """A shadow book's record from data/paper/<name>, in the live-book shape; None before its first session."""
    d = root / "data" / "paper" / b.name
    if not (d / "latest.json").is_file() or not (d / "sessions.json").is_file():
        return None
    latest = json.loads((d / "latest.json").read_text())
    sessions = json.loads((d / "sessions.json").read_text())
    last = sessions[latest["as_of"]]
    buys = [{"sleeve": n, **x} for n, xs in latest["next_open_limit_buys"].items() for x in xs]
    return {
        "as_of": latest["as_of"], "equity": round(last["equity"], 2), "cash": round(last["equity"] - last["invested"], 2),
        "return_pct": round((last["equity"] / b.capital - 1) * 100, 2),
        "positions": [{"symbol": p["symbol"], "sleeve": p["sleeve"], "shares": None, "entry": p["entry"], "close": None,
                       "value": None, "weight_pct": None, "gain_pct": p["gain_pct"]} for p in latest["positions"]],
        "pending": len(buys), "pending_decided": latest["as_of"] if buys else None, "sessions": len(sessions),
        "decisions": 0, "last_decision": None, "curve": [[k, round(v["equity"], 2)] for k, v in sorted(sessions.items())],
        "fills": [], "limit_buys": buys,
    }


def paper_block(cfg: DashboardConfig, root: Path, data_root: Path) -> tuple[dict[str, Any], set[str]]:
    books: list[dict[str, Any]] = []
    names: set[str] = set()
    for b in cfg.paper.books:
        pcfg, strat = load_paper_config(root / b.config, root)
        pv = preview(data_root, cfg.paper.preview_dataset, strat.params, cfg.paper.next_in_line)
        try:
            first = first_month_end(pcfg.start, calendar.load(pcfg.calendar, data_root)).isoformat()
        except calendar.CalendarError:
            first = None
        names.update(p[0] for p in pv["picks"])
        names.update(pv["bench"])
        books.append({"kind": "paper", "name": pcfg.name, "label": b.label, "config": b.config, "strategy": pcfg.strategy_config,
                      "timer": schedule_text(root / b.timer_file), "backtest_run": b.backtest_run, "start": pcfg.start.isoformat(),
                      "capital": pcfg.initial_capital, "first_decision": first, "preview": pv,
                      "live": live_state(data_root, pcfg, cfg.paper.recent_fills)})
    for sb in cfg.paper.shadow_books:
        strat = load_strategy_config(root / sb.preview_strategy, root)
        pv = preview(data_root, cfg.paper.preview_dataset, strat.params, cfg.paper.next_in_line)
        names.update(p[0] for p in pv["picks"])
        names.update(pv["bench"])
        books.append({"kind": "shadow", "name": sb.name, "label": sb.label, "config": sb.config, "strategy": sb.strategy,
                      "timer": sb.schedule, "backtest_run": sb.backtest_run, "start": sb.start.isoformat(),
                      "capital": sb.capital, "first_decision": sb.start.isoformat(), "preview": pv,
                      "live": shadow_state(data_root, sb)})
    return {"dataset": cfg.paper.preview_dataset, "books": books}, names


# --- the bundle -----------------------------------------------------------------------------------------------------

def read_sectors(path: Path) -> dict[str, str]:
    df = pl.read_csv(path)
    return dict(zip(df["Symbol"].to_list(), df["Industry"].to_list()))


def build(cfg: DashboardConfig, root: Path, data_root: Path, config_file: str) -> dict[str, Any]:
    root, data_root = root.resolve(), data_root.resolve()
    runs_dir = data_root / cfg.runs_dir
    base = load_baselines(root)
    records = [Record(e, runs_dir) for e in cfg.runs]
    ids = [r.id for r in records]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ConfigError(f"runs listed twice: {', '.join(dupes)}")
    known = set(ids)
    for b in [*cfg.paper.books, *cfg.paper.shadow_books]:
        if b.backtest_run not in known:
            raise ConfigError(f"paper book {b.label}: backtest_run {b.backtest_run} is not in the runs list")

    tri = read_tri(data_root, base.buy_and_hold.tri_file)
    first = min(min(r.equity["date"]) for r in records)
    cal = build_calendar(records, session_dates(data_root, cfg.paper.preview_dataset, first), tri)
    cal_index = {d: i for i, d in enumerate(cal)}
    weeks = week_ends(cal)
    ed, pd_ = cfg.bundle.equity_decimals, cfg.bundle.price_decimals

    paper, paper_names = paper_block(cfg, root, data_root)

    frames = {r.id: prepare_trades(r) for r in records}
    symbols = sorted({s for f in frames.values() for s in f["symbol"].to_list()} | paper_names)
    sym_index = {s: i for i, s in enumerate(symbols)}

    price_sets: dict[str, Any] = {}
    fund_names: set[str] = set()
    by_ds: dict[str, list[Record]] = {}
    for r in records:
        by_ds.setdefault(r.dataset, []).append(r)
    for ref, recs in sorted(by_ds.items()):
        names = {s for r in recs for s in frames[r.id]["symbol"].to_list()}
        if ref == cfg.paper.preview_dataset:
            names |= paper_names
        px = dataset_prices(data_root, ref, names, first)
        fund_names |= set(px.filter(pl.col("security_id").str.starts_with("isin:INF"))["symbol"].unique().to_list())
        rows: list[tuple[str, int, int]] = []
        for r in recs:
            f = fill_prices(frames[r.id], px)
            frames[r.id] = f
            rows += [(s, cal_index[a], cal_index[b]) for s, a, b in f.select("symbol", "entry_date", "exit_date").iter_rows()]
        windows = weekly_windows(rows, weeks, cfg.bundle.chart_weeks_before, cfg.bundle.chart_weeks_after)
        price_sets[ref] = price_segments(weekly_close(px, cal, weeks), windows, sym_index, pd_)

    n = len(cal)
    runs_out = []
    for r in records:
        f = frames[r.id]
        e = r.equity
        trades = [[sym_index[s], cal_index[a], cal_index[b], round(size or 0), round(pnl), round(ret, 2), hold, status,
                   None if ep is None else round(ep, pd_), None if xp is None else round(xp, pd_)]
                  for s, a, b, size, pnl, ret, hold, status, ep, xp in
                  f.select("symbol", "entry_date", "exit_date", "size", "pnl", "ret", "hold", "status", "entry_px", "exit_px").iter_rows()]
        cfg_file = rel_path(r.manifest["config_file"], data_root, root)
        kind = "Final" if r.manifest["final"] else "Dev"
        runs_out.append({
            "id": r.id, "label": r.entry.label, "group": r.entry.group, "note": r.entry.note or "",
            "tag": r.entry.tag or kind, "strategy": r.manifest["strategy"], "config": cfg_file,
            "config_hash": r.manifest["config_hash"][:12], "dataset": r.dataset, "final": bool(r.manifest["final"]),
            "question": r.manifest.get("question"), "period": [d if isinstance(d, str) else d.isoformat() for d in r.manifest["period"]],
            "equity": aligned(cal_index, n, e["date"].to_list(), e["equity"].to_list(), ed),
            "positions": aligned(cal_index, n, e["date"].to_list(), e["open_positions"].to_list(), None),
            "px_source": "recorded" if "entry_price" in r.trades.columns else "dataset",
            "trades": trades, "metrics": r.metrics["strategy"], "folds": r.metrics.get("folds", {}),
            "baselines": r.metrics.get("baselines", {}),
        })

    sectors_map = read_sectors(root / cfg.sector_map)
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "config": config_file, "name": cfg.name,
        "dataset": cfg.paper.preview_dataset, "data_to": cal[-1].isoformat(),
        "cal": [d.isoformat() for d in cal], "weeks": weeks, "symbols": symbols,
        "sectors": [sectors_map.get(s, "") for s in symbols], "funds": [sym_index[s] for s in sorted(fund_names) if s in sym_index],
        "groups": cfg.groups, "runs": runs_out, "price_sets": price_sets,
        "tri": aligned(cal_index, n, list(tri), list(tri.values()), 2),
        "locked_from": base.locked_from.isoformat(),
        "folds": [[f.name, f.start.isoformat(), f.end.isoformat()] for f in base.folds],
        "adoption_metric": base.adoption.metric, "ui": cfg.ui.model_dump(),
        "chart": {"weeks_before": cfg.bundle.chart_weeks_before, "weeks_after": cfg.bundle.chart_weeks_after},
        "paper": paper,
    }


def write(bundle: dict[str, Any], out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(bundle, separators=(",", ":"), allow_nan=False)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.rename(out)
    return len(text)
