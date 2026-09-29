"""VCP strategy runner: panel -> features -> pattern scan -> signals -> engine -> metrics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from mb.config.loader import Resolved
from mb.data import datasets
from mb.engine.run import evaluate, load_bars
from mb.runs.record import RunResult
from mb.strategy.vcp.features import features
from mb.strategy.vcp.params import Params
from mb.strategy.vcp.pattern import Found, scan

__all__ = ["Params", "run"]


@dataclass
class Scan:
    frame: pl.DataFrame                  # features, sorted by symbol, date
    reasons: pl.DataFrame                # symbol, date, reason for every candidate day in the period
    found: dict[str, list[Found]]        # breakouts dated in the period, by symbol; indices are into that symbol's rows
    offsets: dict[str, int]              # first row of each symbol in `frame`


def detect(cfg: Resolved, root: Path) -> Scan:
    """Scan every symbol. The panel is cut at period.end, so later data cannot leak in."""
    p = cfg.params
    assert isinstance(p, Params)
    period = cfg.strategy.period
    panel = (pl.scan_parquet(datasets.dataset_path(root, cfg.strategy.dataset) / datasets.PANEL_FILE)
             .filter(pl.col("date") <= period.end).collect())
    f = features(panel, p)
    dates = f["date"].to_list()
    in_period = (f["date"] >= period.start).to_numpy()
    cols = {c: f[c].to_numpy() for c in ("high", "low", "close", "volume", "vol_avg")}
    cand = (f["candidate"] & f["date"].is_between(period.start, period.end)).to_numpy()
    rows: list[tuple[str, date, str]] = []
    found: dict[str, list[Found]] = {}
    offsets: dict[str, int] = {}
    start = 0
    for sym, n in f.group_by("symbol", maintain_order=True).len().iter_rows():
        offsets[sym] = start
        s = slice(start, start + n)
        if cand[s].any():
            reasons, hits = scan(*(cols[c][s] for c in ("high", "low", "close", "volume", "vol_avg")), cand[s], p)
            rows.extend((sym, dates[start + d], r) for d, r in reasons)
            hits = [h for h in hits if in_period[start + h.day]]
            if hits:
                found[sym] = hits
        start += n
    reasons = pl.DataFrame(rows, schema={"symbol": pl.String, "date": pl.Date, "reason": pl.String}, orient="row")
    return Scan(f, reasons, found, offsets)


def signals(sc: Scan, p: Params) -> pl.DataFrame:
    """One signal per breakout: a buy-stop at the pivot for the next session, stop at the last contraction's low."""
    f = sc.frame
    market_ok = f["market_ok_prev"].to_numpy()
    dates = f["date"].to_list()
    rows = []
    for sym, hits in sc.found.items():
        o = sc.offsets[sym]
        for h in hits:
            if p.market.enabled and not market_ok[o + h.day]:
                continue
            rows.append((sym, dates[o + h.day], h.pivot, h.stop, 1.0, len(h.contractions)))
    return pl.DataFrame(rows, schema={"symbol": pl.String, "signal_date": pl.Date, "entry_ref": pl.Float64,
                                      "stop": pl.Float64, "size_mult": pl.Float64, "contractions": pl.Int64},
                        orient="row").sort("signal_date", "symbol")


def run(cfg: Resolved, root: Path) -> RunResult:
    p = cfg.params
    assert isinstance(p, Params)
    sigs = signals(detect(cfg, root), p)
    _, result = evaluate(cfg, root, p.engine, sigs, load_bars(root, cfg, p.engine))
    return result
