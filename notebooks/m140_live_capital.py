"""M140 (docs/research/m140.md): M106 through the paper engine (whole shares, raw prices) at live capital sizes, 2010-23.

Usage: uv run python notebooks/m140_live_capital.py CAPITAL [CAPITAL ...]   (rupees, e.g. 250000 1000000)
Writes reports/m140/<capital>.json (metrics, partial-sell count, blocks) and prints one line per capital.
"""
import dataclasses
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from mb.config.loader import load_paper_config, load_strategy_config
from mb.evaluation.metrics import equity_metrics
from mb.data import datasets
from mb.live import paper
from mb.live.paper import Blocked, Book, advance, load_view
from mb.strategy.momentum.targets import targets

ROOT = Path(__file__).resolve().parents[1]
START, END = date(2010, 1, 4), date(2023, 12, 31)
DATASET = "nse_research@2026-10-14"
DP_FEE = 16.0


def main(capitals: list[float]) -> None:
    strat = load_strategy_config(ROOT / "strategies/momentum/configs/m120_ref.yaml", ROOT)
    base, _ = load_paper_config(ROOT / "configs/paper/momentum_b_top25_gold25_jr_gap.yaml", ROOT)
    view = load_view(ROOT, DATASET, START, strat.params)
    # Bhavcopies before mid-2011 carry no ISIN; research runs read the fund-unit list from the whole dataset (M35), so
    # the replay's decisions do the same (live data has ISINs, so the paper book itself does not need this).
    funds = frozenset(pl.scan_parquet(datasets.dataset_path(ROOT, DATASET) / datasets.PANEL_FILE)
                      .filter(pl.col("security_id").str.starts_with("isin:INF")).select("symbol").unique()
                      .collect()["symbol"].to_list())

    def decide(cut, p, start, s):
        t = targets(cut, p, start, s, open_end=True, fund_symbols=funds)[s]
        return t.weights, t.gross

    paper._decide = decide
    view = dataclasses.replace(view, panel=view.panel.filter(pl.col("date") <= END))
    sessions = set(view.panel["date"].unique().to_list())
    holidays = {date(2009, 1, 1) + timedelta(days=i) for i in range((END - date(2009, 1, 1)).days + 1)}
    holidays = {d for d in holidays if d.weekday() < 5 and d not in sessions}
    out_dir = ROOT / "reports" / "m140"
    out_dir.mkdir(parents=True, exist_ok=True)
    for cap in capitals:
        t0 = time.time()
        cfg = base.model_copy(update={"start": START, "initial_capital": cap})
        try:
            _, recs, _ = advance(Book(None, cap), cfg, strat, view, holidays)
            blocked = None
        except Blocked as e:
            recs, blocked = [], str(e)
        res: dict = {"capital": cap, "blocked": blocked, "seconds": round(time.time() - t0)}
        if recs:
            eq = pl.DataFrame({"date": [date.fromisoformat(r["session"]) for r in recs],
                               "equity": [r["equity"] for r in recs]})
            held: dict[str, int] = {}
            partial, zero_buys = 0, 0
            fees = []
            for r in recs:
                for f in r["fills"]:
                    if f["side"] == "sell" and f["symbol"] in {p["symbol"] for p in r["positions"]}:
                        partial += 1
                fees.append(partial * DP_FEE)
                if r["decision"]:
                    zero_buys += sum(1 for s in r["decision"]["picks"]
                                     if not any(o["symbol"] == s for o in r["decision"]["orders"])
                                     and not any(p["symbol"] == s for p in r["positions"]))
            res["metrics"] = equity_metrics(eq, START, END)
            res["partial_sells"] = partial
            res["picks_not_held"] = zero_buys
            res["metrics_dp_every_sale"] = equity_metrics(eq.with_columns(pl.col("equity") - pl.Series(fees)), START, END)
        (out_dir / f"{int(cap)}.json").write_text(json.dumps(res, indent=2, default=str) + "\n")
        m = res.get("metrics", {})
        print(cap, blocked or f"{m.get('cagr_pct', 0):.2f}% / {m.get('max_dd_pct', 0):.2f}% / {m.get('calmar', 0):.3f}",
              res["seconds"], "s", flush=True)


if __name__ == "__main__":
    main([float(x) for x in sys.argv[1:]])
