"""VCP contraction count: how many successively narrower range peaks the last `base_lookback` bars show."""
from __future__ import annotations

import numpy as np
import polars as pl


def count_contractions(range10: np.ndarray, smooth_window: int, min_peak_pct: float) -> int:
    """Ported from v1 `indicators/contraction.py` (count only; quality and progressive flags are not used)."""
    if len(range10) < smooth_window + 2:
        return 0
    smoothed = np.convolve(range10, np.ones(smooth_window) / smooth_window, mode="valid")
    diff = np.diff(smoothed)
    peaks: list[float] = []
    for i in range(1, len(diff)):
        if diff[i - 1] > 0 and diff[i] <= 0:
            peak = smoothed[i]
            if peak < min_peak_pct:
                continue
            left = np.min(smoothed[max(0, i - smooth_window): i])
            right = np.min(smoothed[i: min(len(smoothed), i + smooth_window + 1)])
            if peak - max(left, right) > min_peak_pct * 0.25:
                peaks.append(float(peak))
    if not peaks:
        return 0
    count = 1
    for j in range(len(peaks) - 2, -1, -1):
        if peaks[j + 1] < peaks[j]:
            count += 1
        else:
            break
    return count


def contraction_counts(frame: pl.DataFrame, wanted: pl.Series, base_lookback: int, smooth_window: int,
                       min_peak_pct: float) -> pl.Series:
    """Contraction count for each row, computed only where `wanted` is true (0 elsewhere).

    `frame` must be sorted by symbol, date and carry `symbol` and `range10`. A row's window is the last `base_lookback`
    range10 values of its own symbol; any missing value in the window gives 0, as does a window that is too short.
    """
    symbols = frame["symbol"].to_numpy()
    starts = np.zeros(len(symbols), dtype=np.int64)
    if len(symbols):
        change = np.flatnonzero(symbols[1:] != symbols[:-1]) + 1
        first = np.concatenate([[0], change])
        starts = np.repeat(first, np.diff(np.concatenate([first, [len(symbols)]])))
    r = frame["range10"].fill_null(float("nan")).to_numpy()
    out = np.zeros(len(symbols), dtype=np.int32)
    for i in np.flatnonzero(wanted.fill_null(False).to_numpy()):
        if i - starts[i] < base_lookback - 1:
            continue
        window = r[i - base_lookback + 1: i + 1]
        if np.isnan(window).any():
            continue
        out[i] = count_contractions(window, smooth_window, min_peak_pct)
    return pl.Series("contraction_count", out, dtype=pl.Int32)
