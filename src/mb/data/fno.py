"""M119: per-stock option signals from the NSE F&O bhavcopy (data/raw/nse_fo_bhav).

Implied volatility is Black-76 on each option's close, with the same expiry's stock future close as the forward, so no
dividend or borrow assumption is needed. Only contracts that traded on the day (vol > 0) are used: an untraded row
carries an old or theoretical price.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

AMERICAN = {"CA": "CE", "PA": "PE"}  # stock options before about 2011; priced as European (near the money the gap is small)
IV_LOW, IV_HIGH, IV_STEPS = 0.01, 5.0, 60  # bisection bracket (annualised) and steps: the bracket shrinks below 1e-17


def _files(raw_dir: Path) -> list[Path]:
    files = sorted(raw_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no files in {raw_dir}")
    return files


def chains(raw_dir: Path, sessions: list[date]) -> pl.DataFrame:
    """Traded stock futures and options on `sessions`: d, sym, kind (FUT / CE / PE), expiry, strike, close, oi."""
    # (CA / PA, the American-style labels, count as CE / PE)
    x = pl.concat([pl.scan_parquet(f).filter(pl.col("instrument").is_in(["FUTSTK", "OPTSTK"]) & pl.col("d").is_in(sessions)
                                             & (pl.col("vol") > 0) & (pl.col("c") > 0))
                   .select("d", "sym", pl.when(pl.col("instrument") == "FUTSTK").then(pl.lit("FUT")).otherwise(pl.col("opt").replace(AMERICAN))
                           .alias("kind"), "expiry", "strike", pl.col("c").alias("close"), "oi").collect()
                   for f in _files(raw_dir)])
    return x.sort("d", "sym", "expiry", "kind", "strike")


def option_shares(raw_dir: Path) -> pl.DataFrame:
    """d, sym, shares: underlying shares traded in all of a stock's options that day. `val_lakh` is (strike + premium)
    times shares in both the old and the UDiFF files; the lot size is missing from the old ones."""
    x = pl.concat([pl.scan_parquet(f).filter((pl.col("instrument") == "OPTSTK") & (pl.col("vol") > 0))
                   .group_by("d", "sym").agg((pl.col("val_lakh") * 1e5 / (pl.col("strike") + pl.col("c"))).sum().alias("shares"))
                   .collect() for f in _files(raw_dir)])
    return x.sort("d", "sym")


def _ncdf(x: np.ndarray) -> np.ndarray:
    """Standard normal CDF (Abramowitz & Stegun 7.1.26, absolute error below 1.5e-7)."""
    z = np.abs(x) / np.sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * z)
    poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))))
    erf = 1.0 - poly * np.exp(-z * z)
    return 0.5 * (1.0 + np.sign(x) * erf)


def black76(fwd: np.ndarray, strike: np.ndarray, years: np.ndarray, rate: float, vol: np.ndarray, call: np.ndarray) -> np.ndarray:
    sd = vol * np.sqrt(years)
    d1 = (np.log(fwd / strike) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    disc = np.exp(-rate * years)
    c = disc * (fwd * _ncdf(d1) - strike * _ncdf(d2))
    return np.where(call, c, c - disc * (fwd - strike))  # put by parity


def implied_vol(price: np.ndarray, fwd: np.ndarray, strike: np.ndarray, years: np.ndarray, rate: float,
                call: np.ndarray) -> np.ndarray:
    """Black-76 implied vol by bisection; NaN where the price is outside what any vol in the bracket gives."""
    lo = np.full(price.shape, IV_LOW)
    hi = np.full(price.shape, IV_HIGH)
    ok = (black76(fwd, strike, years, rate, lo, call) < price) & (price < black76(fwd, strike, years, rate, hi, call))
    for _ in range(IV_STEPS):
        mid = 0.5 * (lo + hi)
        above = black76(fwd, strike, years, rate, mid, call) > price
        hi = np.where(above, mid, hi)
        lo = np.where(above, lo, mid)
    return np.where(ok, 0.5 * (lo + hi), np.nan)


def with_iv(ch: pl.DataFrame, rate: float, min_days: int) -> pl.DataFrame:
    """Options of each stock's nearest expiry at least `min_days` calendar days away that has a traded future, with
    fwd (that future's close), m = strike / fwd and iv. Rows whose price admits no vol are dropped."""
    fut = (ch.filter((pl.col("kind") == "FUT") & ((pl.col("expiry") - pl.col("d")).dt.total_days() >= min_days))
           .group_by("d", "sym").agg(pl.all().sort_by("expiry").first()).select("d", "sym", "expiry", pl.col("close").alias("fwd")))
    o = ch.filter(pl.col("kind") != "FUT").join(fut, on=["d", "sym", "expiry"])
    years = ((o["expiry"] - o["d"]).dt.total_days() / 365.0).to_numpy()
    iv = implied_vol(o["close"].to_numpy(), o["fwd"].to_numpy(), o["strike"].to_numpy(), years, rate,
                     (o["kind"] == "CE").to_numpy())
    return o.with_columns(pl.Series("iv", iv), (pl.col("strike") / pl.col("fwd")).alias("m")).filter(pl.col("iv").is_not_nan())


def call_put_spread(o: pl.DataFrame, min_m: float, max_m: float) -> pl.DataFrame:
    """d, sym, value: over strikes with min_m <= m <= max_m where both the call and the put traded, the mean of call IV
    minus put IV weighted by the pair's mean open interest (Cremers & Weinbaum 2010). A stock with no pair is absent."""
    legs = o.filter(pl.col("m").is_between(min_m, max_m))
    pairs = (legs.filter(pl.col("kind") == "CE").select("d", "sym", "strike", pl.col("iv").alias("c_iv"), pl.col("oi").alias("c_oi"))
             .join(legs.filter(pl.col("kind") == "PE").select("d", "sym", "strike", pl.col("iv").alias("p_iv"), pl.col("oi").alias("p_oi")),
                   on=["d", "sym", "strike"]))
    w = (pl.col("c_oi") + pl.col("p_oi")) / 2.0
    return (pairs.group_by("d", "sym").agg(((pl.col("c_iv") - pl.col("p_iv")) * w).sum().alias("num"), w.sum().alias("den"))
            .filter(pl.col("den") > 0).select("d", "sym", (pl.col("num") / pl.col("den")).alias("value")).sort("d", "sym"))


def skew(o: pl.DataFrame, put_min_m: float, put_max_m: float, put_target_m: float,
         call_min_m: float, call_max_m: float, call_target_m: float) -> pl.DataFrame:
    """d, sym, value: IV of the put with m closest to put_target_m in [put_min_m, put_max_m), minus IV of the call with
    m closest to call_target_m in [call_min_m, call_max_m] (Xing, Zhang & Zhao 2010). Ties go to the lower strike."""
    def nearest(kind: str, lo: float, hi: float, target: float, closed: str) -> pl.DataFrame:
        x = o.filter((pl.col("kind") == kind) & pl.col("m").is_between(lo, hi, closed=closed))  # type: ignore[arg-type]
        return (x.sort("d", "sym", (pl.col("m") - target).abs(), "strike").group_by("d", "sym", maintain_order=True)
                .agg(pl.col("iv").first()))
    put = nearest("PE", put_min_m, put_max_m, put_target_m, "left")
    call = nearest("CE", call_min_m, call_max_m, call_target_m, "both")
    return put.join(call, on=["d", "sym"], suffix="_c").select("d", "sym", (pl.col("iv") - pl.col("iv_c")).alias("value")).sort("d", "sym")


def window_sum(x: pl.DataFrame, key: str, value: str, calendar: list[date], sessions: int, at: list[date]) -> pl.DataFrame:
    """at, key, value: the sum of `value` over the `sessions` calendar sessions to each date in `at` (each must be on the
    calendar, with that many sessions before it). Keys with no rows in a window are absent."""
    idx = {d: i for i, d in enumerate(calendar)}
    out = []
    for t in at:
        i = idx[t]
        if i + 1 < sessions:
            raise ValueError(f"{t}: fewer than {sessions} sessions on the calendar to it")
        w = x.filter(pl.col("d").is_between(calendar[i + 1 - sessions], t))
        out.append(w.group_by(key).agg(pl.col(value).sum()).with_columns(pl.lit(t).alias("at")))
    return pl.concat(out).select("at", key, value) if out else pl.DataFrame(schema={"at": pl.Date, key: pl.String, value: pl.Float64})


def panel_symbols(x: pl.DataFrame, links: pl.DataFrame) -> pl.DataFrame:
    """Replace `sym` (the symbol of day `d`) with the panel's symbol: the `final` of the first rename link with
    old = sym and d before `before`, else sym itself. Two rows landing on one (d, symbol) is an error."""
    hit = (x.select("d", "sym").unique().join(links.select("old", "before", "final"), left_on="sym", right_on="old")
           .filter(pl.col("d") < pl.col("before")).sort("before").group_by("d", "sym").agg(pl.col("final").first()))
    out = (x.join(hit, on=["d", "sym"], how="left").with_columns(pl.coalesce("final", "sym").alias("sym")).drop("final"))
    dup = out.group_by("d", "sym").len().filter(pl.col("len") > 1)
    if dup.height:
        raise ValueError(f"F&O symbols map onto one panel symbol: {dup.head(3).rows()}")
    return out
