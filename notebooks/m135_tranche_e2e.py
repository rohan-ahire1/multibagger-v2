"""M135 (docs/research/m135.md): the four draft tranche books end to end on the live daily dataset (read-only, from the
paper deployment), 2026-01..today in a scratch store; replay each; compare each decision with the strategy's own
targets on the research dataset.

uv run python notebooks/m135_tranche_e2e.py [daily_ref] [research_ref]
"""
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

import polars as pl

from mb.config.loader import load_paper_config
from mb.data import datasets
from mb.live import calendar
from mb.live.paper import Blocked, Book, Store, advance, load_view
from mb.live.replay import replay
from mb.strategy.momentum.targets import targets

HERE = Path(__file__).resolve().parents[1]
LIVE = Path.home() / "projects/multibagger-v2"  # read only: its newest daily dataset and holiday snapshot
DAILY = sys.argv[1] if len(sys.argv) > 1 else "nse_daily_delivery@2026-10-22"
RESEARCH = sys.argv[2] if len(sys.argv) > 2 else "nse_research@2026-10-14"
START = date(2026, 1, 1)

rpath = datasets.dataset_path(HERE, RESEARCH) / datasets.PANEL_FILE
rp = pl.scan_parquet(rpath).filter(pl.col("date") >= date(2024, 1, 1)).collect()
funds = frozenset(pl.scan_parquet(rpath).filter(pl.col("security_id").str.starts_with("isin:INF")).select("symbol")
                  .unique().collect()["symbol"].to_list())
rlast = rp["date"].max()

for n in (0, 5, 10, 15):
    cfg, strat = load_paper_config(HERE / f"configs/paper/momentum_m106_tranche_off{n}.yaml", HERE)
    cfg = cfg.model_copy(update={"start": START})
    view = load_view(LIVE, DAILY, cfg.start, strat.params)
    hol = calendar.load(cfg.calendar, LIVE)
    tmp = Path(tempfile.mkdtemp())
    store = Store(tmp, cfg.name)
    try:
        advance(Book(None, cfg.initial_capital), cfg, strat, view, hol, store)
    except Blocked as b:
        print("  blocked", b.session, b.reasons)
    recs = store.days()
    dec = {date.fromisoformat(r["session"]): sorted(r["decision"]["picks"]) for r in recs if r["decision"]}
    left = [calendar.sessions_left_in_month(d, hol) for d in dec]
    rep = replay(cfg, strat, view, recs)
    tg = targets(rp, strat.params, cfg.start, rlast, fund_symbols=funds)
    same, differ, unchecked = 0, [], 0
    for d, picks in dec.items():
        if d not in tg or d >= rlast:
            unchecked += 1
        elif sorted(tg[d].weights) == picks:
            same += 1
        else:
            differ.append((d, sorted(set(picks) - set(tg[d].weights)), sorted(set(tg[d].weights) - set(picks))))
    print(f"offset {n}: sessions {len(recs)} through {recs[-1]['session']}, decisions {len(dec)} "
          f"(sessions left in month at each: {sorted(set(left))}), replay ok {rep['ok']} gap {rep['equity_gap_pct']:+.3f}% "
          f"mismatches {len(rep['decision_mismatches'])}; vs research ({RESEARCH}, through {rlast}): equal {same}, "
          f"differ {len(differ)}, not covered {unchecked}; equity {recs[-1]['equity']:,.0f}")
    for x in differ:
        print("   ", x)
    shutil.rmtree(tmp)
