"""Speed changes that must not move a result: one-pass month-end ranking, the cached 12-1 baseline curve and per-symbol contraction counts."""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import polars as pl
from test_m3_sepa import _cfg, _market, _panel

from mb.data import datasets
from mb.evaluation import baselines
from mb.runs import cache
from mb.strategy.sepa.contraction import contraction_counts, count_contractions
from mb.strategy.momentum.params import Ranking, Universe
from mb.strategy.momentum.targets import cached_ranked, month_ends, ranked


def _per_date_ranking(panel: pl.DataFrame, u: Universe, r: Ranking, start: date, end: date) -> dict[date, list[str]]:
    """The old way: filter the whole frame once per month-end, plain return score, best first, ties by symbol."""
    mom = pl.col("adj_close").shift(r.skip_sessions) / pl.col("adj_close").shift(r.lookback_sessions) - 1.0
    adv = pl.col("turnover").rolling_mean(u.adv_window_sessions, min_samples=u.adv_window_sessions)
    f = panel.sort("symbol", "date").with_columns(mom.over("symbol").alias("score"), adv.over("symbol").alias("adv"))
    eligible = (pl.col("series").is_in(u.allowed_series) & (pl.col("close") >= u.min_price_inr)
                & (pl.col("adv") >= u.min_adv_inr) & pl.col("score").is_not_null() & pl.col("score").is_finite())
    return {d: f.filter((pl.col("date") == d) & eligible).sort("score", "symbol", descending=[True, False])["symbol"].to_list()
            for d in month_ends(f, start, end)}


def _universe(min_price: float = 10.0) -> Universe:
    return Universe(allowed_series=["EQ"], min_price_inr=min_price, min_adv_inr=1.0, adv_window_sessions=5,
                    exclude_fund_units=False)


def test_one_pass_ranking_matches_the_per_date_filter(tmp_path):
    days = _panel(tmp_path / "p.parquet", {"A": 0.003, "B": 0.001, "C": -0.001, "D": 0.001, "E": 0.002}, n=300)
    panel = pl.read_parquet(tmp_path / "p.parquet")
    r = Ranking(lookback_sessions=40, skip_sessions=5, score="return")
    got = ranked(panel, _universe(), r, days[0], days[-1])
    assert got == _per_date_ranking(panel, _universe(), r, days[0], days[-1])
    assert len(got) >= 12 and any(got.values())


def test_a_month_end_with_no_eligible_name_gives_an_empty_list(tmp_path):
    days = _panel(tmp_path / "p.parquet", {"A": 0.0}, n=120)
    panel = pl.read_parquet(tmp_path / "p.parquet")
    got = ranked(panel, _universe(min_price=1000.0), Ranking(lookback_sessions=20, skip_sessions=5, score="return"),
                 days[0], days[-1])
    assert got and all(v == [] for v in got.values())


def _dataset(tmp_path):
    """A panel in a dataset folder with a manifest, the way real datasets are laid out."""
    ds = tmp_path / "ds"
    ds.mkdir()
    days = _panel(ds / datasets.PANEL_FILE, {"UP": 0.004, "FLAT": 0.0, "DOWN": -0.002})
    sha = datasets.sha256_file(ds / datasets.PANEL_FILE)
    (ds / "manifest.json").write_text(json.dumps({"outputs": {datasets.PANEL_FILE: {"sha256": sha}}}))
    return ds / datasets.PANEL_FILE, days


def test_cached_baseline_curve_equals_the_built_one(tmp_path):
    panel, days = _dataset(tmp_path)
    cfg, market = _cfg("unused"), _market(True)
    built, rebalances = baselines.momentum_curve(cfg, market, panel, days[0], days[-1])
    first = baselines.cached_momentum_curve(tmp_path, cfg, market, panel, days[0], days[-1])
    files = sorted(p.name for p in (tmp_path / baselines.CACHE_DIR).iterdir())
    assert len(files) == 2 and not any(n.startswith(".") for n in files)
    second = baselines.cached_momentum_curve(tmp_path, cfg, market, panel, days[0], days[-1])
    for curve, n in (first, second):
        assert curve.equals(built) and curve.schema == built.schema and n == rebalances


def test_cache_key_follows_settings_and_skips_panels_without_a_manifest(tmp_path):
    panel, days = _dataset(tmp_path)
    cfg = _cfg("unused")
    baselines.cached_momentum_curve(tmp_path, cfg, _market(True), panel, days[0], days[-1])
    paid_only = baselines.cached_momentum_curve(tmp_path, cfg, _market(True), panel, days[0], days[-1])
    free, _ = baselines.cached_momentum_curve(tmp_path, cfg, _market(False), panel, days[0], days[-1])
    assert len(list((tmp_path / baselines.CACHE_DIR).glob("*.parquet"))) == 2
    assert free["equity"][-1] > paid_only[0]["equity"][-1]

    bare = tmp_path / "bare"
    bare.mkdir()
    _panel(bare / "p.parquet", {"UP": 0.004})
    baselines.cached_momentum_curve(bare, cfg, _market(True), bare / "p.parquet", days[0], days[-1])
    assert not (bare / baselines.CACHE_DIR).exists()


def test_cache_off_builds_from_scratch_and_writes_nothing(tmp_path):
    panel, days = _dataset(tmp_path)
    cfg, market = _cfg("unused"), _market(True)
    built, rebalances = baselines.momentum_curve(cfg, market, panel, days[0], days[-1])
    with cache.off():
        curve, n = baselines.cached_momentum_curve(tmp_path, cfg, market, panel, days[0], days[-1])
    assert curve.equals(built) and n == rebalances
    assert not (tmp_path / baselines.CACHE_DIR).exists()
    baselines.cached_momentum_curve(tmp_path, cfg, market, panel, days[0], days[-1])
    assert len(list((tmp_path / baselines.CACHE_DIR).glob("*.parquet"))) == 1


def test_per_symbol_contraction_counts_match_the_per_window_count():
    rng = np.random.default_rng(7)
    sizes = [5, 80, 140, 60]
    r = np.abs(np.concatenate([np.cumsum(rng.normal(0, 0.01, n)) for n in sizes])) + 0.02
    r[[100, 101, 230]] = np.nan
    frame = pl.DataFrame({"symbol": np.repeat(["A", "B", "C", "D"], sizes), "range10": r})
    wanted = pl.Series(rng.random(len(r)) < 0.8)
    for lookback, smooth, peak in ((30, 3, 0.02), (20, 1, 0.01), (40, 5, 0.03), (4, 3, 0.02)):
        got = contraction_counts(frame, wanted, lookback, smooth, peak).to_list()
        want = [0] * len(r)
        for i in range(len(r)):
            w, sym = r[max(0, i - lookback + 1): i + 1], frame["symbol"][i]
            same = (frame["symbol"][max(0, i - lookback + 1): i + 1] == sym).all()
            if wanted[i] and len(w) == lookback and same and not np.isnan(w).any():
                want[i] = count_contractions(w, smooth, peak)
        assert got == want
        assert lookback == 4 or any(want)


def test_cached_ranking_equals_the_built_one_and_is_skipped_when_off(tmp_path):
    days = _panel(tmp_path / "p.parquet", {"A": 0.003, "B": 0.001, "C": -0.001, "D": 0.002}, n=300)
    panel = pl.read_parquet(tmp_path / "p.parquet")
    r = Ranking(lookback_sessions=40, skip_sessions=5, score="return")
    args = (_universe(), r, days[0], days[-1], 2, 0, None, None, None)
    built = ranked(panel, *args)
    store = tmp_path / cache.ROOT / "rankings"
    with cache.off():
        assert cached_ranked((tmp_path, "id"), panel, *args) == built
    assert not store.exists()
    for _ in range(2):
        got = cached_ranked((tmp_path, "id"), panel, *args)
        assert got == built and list(got) == list(built)
    assert len(list(store.iterdir())) == 1
    cached_ranked((tmp_path, "other"), panel, *args)
    cached_ranked((tmp_path, "id"), panel, _universe(min_price=20.0), *args[1:])
    assert len(list(store.iterdir())) == 3
    assert cached_ranked(None, panel, *args) == built
