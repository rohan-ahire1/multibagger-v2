"""M1: adapters, adjustment, checks and dataset builds."""
import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest
import yaml

from data_fixture import DELIST_AFTER, SPLIT_SESSION, BONUS_SESSION, sessions, write_data_config, write_raw, zip_bytes
from mb.config.loader import ConfigError, load_data_config
from mb.config.models import AdjustmentConfig
from mb.data import adjust, build, datasets
from mb.data.corporate_actions import OverrideError, load_overrides
from mb.sources import nse_bhavcopy, nse_corporate_actions as nca

ADJ = AdjustmentConfig(match_window_sessions=3, match_tolerance=1.25, min_detectable=1.2,
                       unexplained_jump=1.5, dividend_max_price_fraction=0.5)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    write_raw(tmp_path)
    return tmp_path


def do_build(root: Path, version: str) -> Path:
    cfg, h = load_data_config(write_data_config(root))
    return build.build(cfg, h, root, version)


# --- corporate-action parser ---------------------------------------------------------------

@pytest.mark.parametrize("text,kind,fields", [
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share", "split",
     {"old_face_value": 10.0, "new_face_value": 1.0}),
    ("Bonus 1:2", "bonus", {"ratio_num": 1, "ratio_den": 2}),
    ("Bonus 1:1 / Face Value Split From Rs.10/- To Re.1/-", "bonus_split",
     {"ratio_num": 1, "ratio_den": 1, "old_face_value": 10.0, "new_face_value": 1.0}),
    ("Dividend - Rs 5 Per Share", "dividend", {"dividend_amount": 5.0}),
    ("Annual General Meeting", "unparsed", {}),
])
def test_parse_subject(text, kind, fields):
    out = nca.parse_subject(text)
    assert out["action_type"] == kind
    assert out["original_source_text"] == text
    for k, v in fields.items():
        assert out[k] == v


def test_merge_fetched_keeps_other_windows():
    def row(sym, d):
        return {**{k: None for k in nca.SCHEMA}, "symbol": sym, "ex_date": d, "action_type": "split"}
    existing = pl.DataFrame([row("OLD", date(2010, 3, 1)), row("STALE", date(2020, 3, 1))], schema=nca.SCHEMA)
    fetched = pl.DataFrame([row("NEW", date(2020, 4, 1))], schema=nca.SCHEMA)
    merged = nca.merge_fetched(existing, fetched, [(date(2020, 1, 1), date(2020, 6, 30))])
    assert sorted(merged["symbol"]) == ["NEW", "OLD"]


def test_override_unknown_source_is_error(tmp_path: Path):
    p = tmp_path / "o.csv"
    p.write_text("symbol,ex_date,action_type,source,adjustment_factor\nX,2020-01-01,split,mystery,0.5\n")
    with pytest.raises(OverrideError, match="mystery"):
        load_overrides(p, ["manual"])


def test_override_seed_rows_inert(tmp_path: Path):
    p = tmp_path / "o.csv"
    p.write_text("symbol,ex_date,action_type,source,adjustment_factor\nX,2020-01-01,split,seed,0.5\n"
                 "Y,2020-01-01,split,manual,0.5\n")
    assert load_overrides(p, ["manual"])["symbol"].to_list() == ["Y"]


# --- multipliers and matching --------------------------------------------------------------

def test_multipliers():
    assert adjust.event_price_multiplier({"action_type": "split", "old_face_value": 10, "new_face_value": 2}) == 0.2
    assert adjust.event_price_multiplier({"action_type": "bonus", "ratio_num": 1, "ratio_den": 2}) == pytest.approx(2 / 3)
    both = {"action_type": "bonus_split", "ratio_num": 1, "ratio_den": 1, "old_face_value": 10, "new_face_value": 5}
    assert adjust.event_price_multiplier(both) == 0.25
    assert adjust.event_price_multiplier({"action_type": "split", "adjustment_factor": 0.1}) == 0.1
    assert adjust.event_price_multiplier({"action_type": "split"}) is None


def _prices(symbol, closes, start=date(2023, 1, 2)):
    d = sessions()[:len(closes)]
    return pl.DataFrame({"symbol": symbol, "date": d, "open": closes, "close": closes})


def test_match_finds_jump_one_session_off_listed_date():
    closes = [100.0] * 10 + [50.0] * 10
    prices = _prices("AAA", closes)
    ev = pl.DataFrame({"symbol": ["AAA"], "ex_date": [sessions()[9]], "expected": [0.5], "sources": ["x"]})
    m = adjust.match_share_events(prices, ev, ADJ)
    assert m["status"][0] == "matched" and m["effective_date"][0] == sessions()[10] and m["offset"][0] == 1


def test_match_reports_event_with_no_jump():
    prices = _prices("AAA", [100.0] * 20)
    ev = pl.DataFrame({"symbol": ["AAA"], "ex_date": [sessions()[10]], "expected": [0.5], "sources": ["x"]})
    assert adjust.match_share_events(prices, ev, ADJ)["status"][0] == "unmatched"


def test_two_events_on_one_jump_apply_once():
    prices = _prices("AAA", [100.0] * 10 + [50.0] * 10)
    ev = pl.DataFrame({"symbol": ["AAA", "AAA"], "ex_date": [sessions()[10], sessions()[9]],
                       "expected": [0.5, 0.5], "sources": ["a", "b"]})
    m = adjust.match_share_events(prices, ev, ADJ)
    assert sorted(m["status"]) == ["duplicate", "matched"]


def test_dividend_uses_close_before_ex_date():
    prices = _prices("AAA", [100.0, 100.0, 90.0, 90.0])
    acts = pl.DataFrame({"symbol": ["AAA"], "ex_date": [sessions()[2]], "action_type": ["dividend"],
                         "dividend_amount": [10.0]})
    steps = adjust.dividend_steps(prices, acts, ADJ)
    assert steps["mult"][0] == pytest.approx(0.9)  # 1 - 10/100, not 1 - 10/90


# --- adapters -------------------------------------------------------------------------------

def test_parse_both_bhavcopy_formats(tmp_path: Path):
    cfg, _ = load_data_config(write_data_config(tmp_path))
    legacy = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,ISIN\nAAA,EQ,10,11,9,10.5,100,1050,02-JAN-2023,INE001\nBAD,BE,1,1,1,1,1,1,02-JAN-2023,INE002\n"
    p = tmp_path / "2023-01-02.zip"
    p.write_bytes(zip_bytes("x.csv", legacy))
    bars = nse_bhavcopy.parse_zip(p, cfg.bhavcopy)
    assert bars.columns == ["date", "symbol", "security_id", "series", "open", "high", "low", "close", "volume",
                            "turnover", "source"]
    assert bars["symbol"].to_list() == ["AAA"] and bars["security_id"][0] == "isin:INE001"

    udiff = ("TradDt,TckrSymb,SctySrs,ISIN,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol,TtlTrfVal\n"
             "2024-01-02,AAA,EQ,,10,11,9,10.5,100,1050\n")
    q = tmp_path / "2024-01-02.zip"
    q.write_bytes(zip_bytes("y.csv", udiff))
    out = nse_bhavcopy.parse_zip(q, cfg.bhavcopy)
    assert out["security_id"][0] == "fallback:AAA:EQ" and out["date"][0] == date(2024, 1, 2)


def test_url_formats():
    cfg, _ = load_data_config(Path(__file__).resolve().parents[1] / "configs/data/nse_research.yaml")
    assert nse_bhavcopy.build_url(cfg.bhavcopy, date(2023, 3, 1)).endswith("/2023/MAR/cm01MAR2023bhav.csv.zip")
    assert nse_bhavcopy.build_url(cfg.bhavcopy, date(2024, 3, 1)).endswith("BhavCopy_NSE_CM_0_0_0_20240301_F_0000.csv.zip")


# --- dataset build (golden fixture) ----------------------------------------------------------

def test_build_adjusts_split_bonus_and_keeps_delisted(root: Path):
    out = do_build(root, "v1")
    panel = pl.read_parquet(out / datasets.PANEL_FILE)
    ss = sessions()
    for sym, at in (("AAA", SPLIT_SESSION), ("BBB", BONUS_SESSION)):
        s = panel.filter(pl.col("symbol") == sym).sort("date")
        jump = s["adj_close"][at] / s["adj_close"][at - 1]
        assert 0.99 < jump < 1.02, (sym, jump)  # continuous across the event
        assert s["close"][at] / s["close"][at - 1] < 0.6  # raw columns keep the cliff
        assert s["adj_close"][-1] == pytest.approx(s["close"][-1])  # latest bar unchanged
    ccc = panel.filter(pl.col("symbol") == "CCC")
    assert ccc["date"].max() == ss[DELIST_AFTER - 1]
    aaa = panel.filter(pl.col("symbol") == "AAA").sort("date")
    assert aaa["adj_volume"][0] == aaa["volume"][0] * 2  # share events adjust volume
    manifest = datasets.read_manifest(out)
    assert manifest["share_event_status"] == {"matched": 2}
    assert all(c["status"] in {"pass", "skipped"} for c in manifest["checks"])


def test_rebuild_is_identical(root: Path):
    a, b = do_build(root, "v1"), do_build(root, "v2")
    assert datasets.read_manifest(a)["outputs"] == datasets.read_manifest(b)["outputs"]
    assert datasets.read_manifest(a)["inputs"] == datasets.read_manifest(b)["inputs"]


def test_existing_version_is_immutable(root: Path):
    do_build(root, "v1")
    with pytest.raises(ConfigError, match="immutable"):
        do_build(root, "v1")


def test_dividend_reaches_panel_price_only(root: Path):
    panel = pl.read_parquet(do_build(root, "v1") / datasets.PANEL_FILE)
    d = panel.filter(pl.col("symbol") == "DDD").sort("date")
    assert d["adj_close"][0] < d["close"][0]  # earlier bars scaled down by the dividend
    assert d["adj_volume"][0] == d["volume"][0]  # volume untouched


def test_check_failure_blocks_version(root: Path):
    cfg_path = write_data_config(root)
    (root / "data/raw/nse_bhavcopy/2023/2023-02-01.zip").unlink()  # a missing session
    cfg, h = load_data_config(cfg_path)
    cfg = cfg.model_copy(update={"checks": cfg.checks.model_copy(update={"max_session_gap_days": 1})})
    with pytest.raises(build.CheckFailure, match="max_session_gap_days"):
        build.build(cfg, h, root, "v1")
    assert not (root / "data/datasets/fixture/v1").exists()


def test_verify_outputs_detects_tampering(root: Path):
    out = do_build(root, "v1")
    assert datasets.verify_outputs(out) == []
    (out / "ca_matches.parquet").write_bytes(b"tampered")
    assert datasets.verify_outputs(out) == ["ca_matches.parquet"]


def test_unknown_data_config_key_fails(root: Path):
    p = write_data_config(root)
    d = yaml.safe_load(p.read_text())
    d["checks"]["surprise"] = 1
    p.write_text(yaml.safe_dump(d))
    with pytest.raises(ConfigError, match="surprise"):
        load_data_config(p)
