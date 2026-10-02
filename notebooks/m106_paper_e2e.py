"""M106 (docs/research/m106.md), as M51. End-to-end: build nse_daily_delivery, run the draft book over 2025-01..2026-07 in a scratch store, replay, and
compare its decisions with the pin's targets on the research dataset."""
import shutil, tempfile
from datetime import date
from pathlib import Path

import polars as pl

from mb.config.loader import load_data_config, load_paper_config
from mb.data import datasets
from mb.live import calendar
from mb.live.daily import ensure_dataset
from mb.live.paper import Book, Store, advance, load_view
from mb.live.replay import replay
from mb.strategy.momentum.targets import targets

ROOT = Path.home() / "projects/multibagger-v2"
cfg, strat = load_paper_config(ROOT / "configs/paper/momentum_b_top25_gold25_jr_gap.yaml", ROOT)
cfg = cfg.model_copy(update={"start": date(2026, 1, 30)})
dcfg, dhash = load_data_config(ROOT / cfg.data_config)
ref, built = ensure_dataset(dcfg, dhash, ROOT)
print("dataset", ref, "built", built)
view = load_view(ROOT, ref, cfg.start, strat.params)
print("view cols", view.panel.columns, "rows", view.panel.height, "deliv non-null", view.panel["deliv_qty"].is_not_null().sum())
tmp = Path(tempfile.mkdtemp())
store = Store(tmp, cfg.name)
hol = calendar.load(cfg.calendar, ROOT)
from mb.live.paper import Blocked
try:
    book, recs, notes = advance(Book(None, cfg.initial_capital), cfg, strat, view, hol, store)
except Blocked as b:
    print("blocked", b.session, b.reasons)
    book = store.load_book(cfg)
recs = store.days()
dec = {r["session"]: sorted(r["decision"]["picks"]) for r in recs if r["decision"]}
for r in recs:
    if r["decision"]:
        print(r["session"], "gold weight", round(r["decision"]["weights"].get("GOLDBEES", 0.0), 4), "names", len(r["decision"]["picks"]))
print("sessions", len(recs), "decisions", len(dec), "equity", round(book.cash + sum(p.shares * 0 for p in book.positions.values())))
rep = replay(cfg, strat, view, store.days())
print("replay ok", rep["ok"], "gap %", rep["equity_gap_pct"], "mismatches", len(rep["decision_mismatches"]))

# The pin's own targets on the research dataset for the same month-ends.
rpath = datasets.dataset_path(ROOT, "nse_research@2026-10-02b") / datasets.PANEL_FILE
rp = pl.scan_parquet(rpath).filter(pl.col("date") >= date(2023, 1, 1)).collect()
funds = frozenset(pl.scan_parquet(rpath).filter(pl.col("security_id").str.starts_with("isin:INF")).select("symbol").unique().collect()["symbol"].to_list())
last = rp["date"].max()
tg = targets(rp, strat.params, cfg.start, last, fund_symbols=funds)
same = diff = 0
for s, picks in dec.items():
    d = date.fromisoformat(s)
    if d not in tg:
        continue
    r = sorted(tg[d].weights)
    if r == picks:
        same += 1
    else:
        diff += 1
        print(s, "paper-only", sorted(set(picks) - set(r)), "research-only", sorted(set(r) - set(picks)))
print("research data through", last, "decisions equal", same, "differ", diff)
shutil.rmtree(tmp)
