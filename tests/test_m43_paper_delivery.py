"""M43: the paper book with the M40 delivery filter: daily delivery downloads, rebuilds and the book's panel columns."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
import yaml
from data_fixture import data_config, sessions, write_raw
from test_m3_sepa import _cfg, _market
from test_m6_paper import _days, _hol, _paper_cfg, _view
from test_m6_paper import _panel as _paper_panel
from test_m40_momentum import _m40

from mb.config.loader import Resolved, load_data_config, load_strategy_config
from mb.config.models import Period, StrategyConfig
from mb.live import daily
from mb.live.daily import ensure_dataset, fetch_delivery
from mb.live.paper import Book, Store, advance, check_supported, load_view
from mb.live.replay import replay
from mb.sources import nse_delivery
from mb.strategy.momentum.params import ParamsM40

ROOT = Path(__file__).resolve().parents[1]
DELIVERY = {"raw_dir": "data/raw/nse_delivery", "archive_base_url": "http://d", "timeout_s": 1.0, "max_retries": 1,
            "request_sleep_s": 0.0}


def _params(frac: float | None) -> ParamsM40:
    p = _m40(frac).model_dump()
    p["portfolio"] |= {"fixed_weights": {}}
    p["ranking"] |= {"lookback_sessions": 20, "skip_sessions": 2}
    return ParamsM40.model_validate(p)


def _mto(root: Path, d: date, share: float = 0.5) -> None:
    f = nse_delivery.file_path(root / DELIVERY["raw_dir"], d)
    f.parent.mkdir(parents=True, exist_ok=True)
    recs = "".join(f"20,{i},{s},EQ,100000,{int(100000 * share)},{share * 100:.2f}\n" for i, s in enumerate(("AAA", "BBB", "CCC", "DDD")))
    f.write_text(f"Security Wise Delivery Position - Compulsory Rolling Settlement\n10,MTO,{d:%d%m%Y},1,1\n"
                 f"Trade Date <x>,Settlement Type <N>\nRecord Type,Sr No,Name of Security,Quantity Traded,"
                 f"Deliverable Quantity,% of Deliverable\n{recs}")


def _delivery_config(root: Path) -> Path:
    p = root / "data.yaml"
    p.write_text(yaml.safe_dump(data_config() | {"link_renames_by_isin": True, "rename_max_gap_days": 31,
                                                 "delivery": DELIVERY}))
    return p


def test_the_m40_pin_is_accepted_by_paper():
    check_supported(load_strategy_config(ROOT / "strategies/momentum/configs/m40_deliv40_gold20_b2.yaml", ROOT).params)


def test_the_book_with_the_delivery_filter_matches_the_replay_and_skips_low_delivery_names(tmp_path):
    days = _days(date(2023, 6, 1), 200)
    drifts = {"AAA": 0.004, "BBB": 0.002, "CCC": -0.001, "DDD": 0.003, "EEE": 0.0}
    share = {"AAA": 0.1, "BBB": 0.6, "CCC": 0.5, "DDD": 0.7, "EEE": 0.4}  # AAA rises fastest but delivers least
    panel = _paper_panel(days, drifts).with_columns(pl.lit(1000).cast(pl.Int64).alias("volume"))
    panel = panel.with_columns((pl.col("symbol").replace_strict(share) * 1000).cast(pl.Int64).alias("deliv_qty"))
    cfg = _paper_cfg(date(2023, 8, 1))
    s = StrategyConfig(name="momentum", version="t", dataset="x@1", market="m",
                       period=Period(start=date(2020, 1, 1), end=date(2020, 1, 2)), params={})
    strat = Resolved(s, _params(0.2), _market(True), _cfg("x"), Path("s.yaml"))
    store = Store(tmp_path, cfg.name)
    book, recs, _ = advance(Book(None, cfg.initial_capital), cfg, strat, _view(panel), _hol(days), store)
    decisions = [r["decision"] for r in recs if r["decision"]]
    assert len(decisions) >= 5 and all("AAA" not in d["picks"] and len(d["picks"]) == 2 for d in decisions)
    rep = replay(cfg, strat, _view(panel), store.days())
    assert rep["decision_mismatches"] == [] and rep["ok"]


def test_the_view_reads_delivery_only_when_the_filter_is_on_and_refuses_a_dataset_without_it(tmp_path):
    write_raw(tmp_path)
    for d in sessions():
        _mto(tmp_path, d)
    plain = tmp_path / "plain.yaml"
    plain.write_text(yaml.safe_dump(data_config() | {"name": "plain"}))
    ref, _ = ensure_dataset(*load_data_config(plain), tmp_path)
    with pytest.raises(ValueError, match="has no deliv_qty"):
        load_view(tmp_path, ref, sessions()[30], _params(0.4))
    assert "deliv_qty" not in load_view(tmp_path, ref, sessions()[30], _params(None)).panel.columns
    ref, _ = ensure_dataset(*load_data_config(_delivery_config(tmp_path)), tmp_path)
    view = load_view(tmp_path, ref, sessions()[30], _params(0.4))
    assert view.panel["deliv_qty"].drop_nulls().len() == view.panel.height


def test_a_late_delivery_file_is_fetched_and_rebuilds_the_daily_dataset(tmp_path, monkeypatch):
    write_raw(tmp_path)
    for d in sessions()[:-1]:
        _mto(tmp_path, d)
    dcfg, dhash = load_data_config(_delivery_config(tmp_path))
    ref, built = ensure_dataset(dcfg, dhash, tmp_path)
    assert built

    asked: list[list[date]] = []

    def fake_fetch(cfg, raw, wanted):
        asked.append(wanted)
        for d in wanted:
            _mto(tmp_path, d)
        return {"downloaded": wanted, "missing": []}

    monkeypatch.setattr(daily.nse_delivery, "fetch", fake_fetch)
    assert fetch_delivery(dcfg, tmp_path) == {"downloaded": [sessions()[-1].isoformat()], "missing": []}
    assert asked == [[sessions()[-1]]]
    ref2, built2 = ensure_dataset(dcfg, dhash, tmp_path)
    assert built2 and ref2 != ref
    assert fetch_delivery(dcfg, tmp_path) == {"downloaded": [], "missing": []} and len(asked) == 1
