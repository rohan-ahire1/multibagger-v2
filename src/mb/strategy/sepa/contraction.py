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

    Gives exactly `count_contractions` on each window, but smooths each symbol once instead of once per row: a smoothed
    value only depends on its own `smooth_window` inputs, so the per-window and per-symbol values are the same floats.
    Peaks far enough from a window's edges qualify the same way in every window, so only edge peaks are rechecked.
    """
    symbols = frame["symbol"].to_numpy()
    out = np.zeros(len(symbols), dtype=np.int32)
    if not len(symbols) or base_lookback < smooth_window + 2:
        return pl.Series("contraction_count", out, dtype=pl.Int32)
    first = np.concatenate([[0], np.flatnonzero(symbols[1:] != symbols[:-1]) + 1])
    ends = np.concatenate([first[1:], [len(symbols)]])
    starts = np.repeat(first, ends - first)
    r = frame["range10"].fill_null(float("nan")).to_numpy()
    gaps = np.concatenate([[0], np.cumsum(np.isnan(r))])
    rows = np.flatnonzero(wanted.fill_null(False).to_numpy())
    rows = rows[rows - starts[rows] >= base_lookback - 1]
    rows = rows[gaps[rows + 1] == gaps[rows + 1 - base_lookback]]
    kernel, span, sw, edge = np.ones(smooth_window) / smooth_window, base_lookback - smooth_window + 1, smooth_window, \
        min_peak_pct * 0.25
    for seg in np.split(rows, np.searchsorted(rows, first[1:])):
        if not len(seg):
            continue
        s, e = starts[seg[0]], ends[np.searchsorted(first, seg[0], side="right") - 1]
        sm = np.convolve(r[s:e], kernel, mode="valid")
        d = np.diff(sm)
        left = np.full(len(sm), np.nan)
        right = np.full(len(sm), np.nan)
        left[sw:] = np.lib.stride_tricks.sliding_window_view(sm, sw).min(axis=1)[: len(sm) - sw]
        right[: len(sm) - sw] = np.lib.stride_tricks.sliding_window_view(sm, sw + 1).min(axis=1)
        tops = np.zeros(len(sm), dtype=bool)
        tops[1:-1] = (d[:-1] > 0) & (d[1:] <= 0) & (sm[1:-1] >= min_peak_pct)
        cand = np.flatnonzero(tops)
        good = (sm - np.fmax(left, right) > edge).tolist()
        smv = sm.tolist()
        lo = np.searchsorted(cand, seg - s - base_lookback + 2).tolist()
        hi = np.searchsorted(cand, seg - s - smooth_window, side="right").tolist()
        cand = cand.tolist()
        for i, a, b in zip(seg.tolist(), lo, hi):
            ws = i - s - base_lookback + 1
            we = ws + span
            count, nxt = 0, 0.0
            for p in reversed(cand[a:b]):
                if p - sw >= ws and p + sw + 1 <= we:
                    if not good[p]:
                        continue
                elif not smv[p] - max(min(smv[max(ws, p - sw): p]), min(smv[p: min(we, p + sw + 1)])) > edge:
                    continue
                if count and not nxt < smv[p]:
                    break
                count, nxt = count + 1, smv[p]
            out[i] = count
    return pl.Series("contraction_count", out, dtype=pl.Int32)
