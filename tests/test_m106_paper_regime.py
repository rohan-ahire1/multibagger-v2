"""M106: the paper book runs the regime's gold switch and matches its backtest replay (docs/research/m106.md)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import yaml
from test_m3_sepa import _cfg, _market
from test_m6_paper import _days, _hol, _panel, _paper_cfg, _view

from mb.config.loader import Resolved, load_strategy_config
from mb.config.models import Period, StrategyConfig
from mb.live.paper import Book, Store, advance, check_supported
from mb.live.replay import replay
from mb.strategy.momentum.params import ParamsM89

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "strategies/momentum/configs/m106_gap30_g25_jr_b2.yaml"


def _strat() -> Resolved:
    p = yaml.safe_load(CFG.read_text())["params"]
    p["universe"] |= {"min_price_inr": 1, "min_adv_inr": 1, "adv_window_sessions": 5, "delivery_drop_frac": None,
                      "max_gap_days": None}
    p["ranking"] |= {"lookback_sessions": 40, "skip_sessions": 5, "max_window_sessions": 5}
    p["portfolio"] |= {"top_n": 2, "hold_rank_max": 2, "inverse_vol_sessions": 20, "fixed_weights": {"GOLD": 0.25}}
    p["regime"] |= {"benchmark_symbol": "BENCH", "sma_sessions": 20, "risk_off_symbol": "GOLD"}
    s = StrategyConfig(name="momentum", version="t", dataset="x@1", market="m",
                       period=Period(start=date(2020, 1, 1), end=date(2020, 1, 2)), params={})
    return Resolved(s, ParamsM89.model_validate(p), _market(True), _cfg("x"), Path("s.yaml"))


def _regime_panel(days: list[date]) -> pl.DataFrame:
    panel = _panel(days, {"AAA": 0.004, "BBB": 0.002, "CCC": -0.001, "DDD": 0.003, "GOLD": 0.001, "BENCH": 0.0})
    # BENCH rises for 120 sessions, then falls: risk-on month-ends first, then risk-off ones.
    i = {d: k for k, d in enumerate(days)}
    bench = pl.Series([100.0 * (1.003 ** min(i[d], 120)) * (0.99 ** max(0, i[d] - 120)) for d in panel.filter(pl.col("symbol") == "BENCH")["date"]])
    panel = panel.with_columns(pl.when(pl.col("symbol").is_in(["GOLD", "BENCH"])).then(pl.lit("isin:INF") + pl.col("symbol"))
                               .otherwise(pl.col("security_id")).alias("security_id"))
    b = panel.filter(pl.col("symbol") == "BENCH").with_columns(*(bench.alias(c) for c in ("open", "close", "adj_open", "adj_close")))
    return pl.concat([panel.filter(pl.col("symbol") != "BENCH"), b]).sort("symbol", "date")


def test_the_draft_strategy_is_supported_by_paper():
    check_supported(load_strategy_config(CFG, ROOT).params)


def test_the_paper_book_switches_to_gold_when_risk_off_and_matches_the_replay(tmp_path):
    days = _days(date(2023, 6, 1), 220)
    panel = _regime_panel(days)
    cfg, strat = _paper_cfg(date(2023, 8, 1), initial_capital=1e7), _strat()
    store = Store(tmp_path, cfg.name)
    book, recs, _ = advance(Book(None, cfg.initial_capital), cfg, strat, _view(panel), _hol(days), store)
    decisions = [r["decision"] for r in recs if r["decision"]]
    gold = [d["weights"]["GOLD"] for d in decisions]
    # Risk-on: the 25% sleeve; risk-off: the sleeve plus half of the stock share, 0.25 + 0.75 / 2.
    assert 0.25 in gold and any(abs(g - 0.625) < 1e-12 for g in gold)
    assert gold == sorted(gold) and all(abs(d["gross"] - 1.0) < 1e-12 for d in decisions)
    held = book.positions["GOLD"].shares * book.positions["GOLD"].last_close / book.equity()
    assert 0.55 < held < 0.7
    rep = replay(cfg, strat, _view(panel), store.days())
    assert rep["decision_mismatches"] == [] and rep["ok"]
