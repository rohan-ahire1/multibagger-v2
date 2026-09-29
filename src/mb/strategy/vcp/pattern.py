"""The VCP pattern on one symbol's sessions: swings, the base and its contractions, volume dry-up, the breakout.

Everything on breakout day D uses only sessions up to D-1, except the breakout test itself (D's close and volume). A swing
at session t is only known at t + k (k sessions each side), so a scan at D sees swings with t <= D - 1 - k.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from mb.strategy.vcp.params import Params

# Why a candidate day (trend template passed the day before) is not a breakout. The first failed rule is recorded.
REASONS = (
    "breakout", "no_swing_high", "above_base_high", "base_too_short", "too_few_contractions", "too_many_contractions",
    "first_too_deep", "not_contracting", "last_too_deep", "not_tightening", "pivot_too_low", "volume_not_lower",
    "no_quiet_day", "no_close_above_pivot", "pivot_already_crossed", "breakout_volume_low",
)
# Funnel stage a reason belongs to: 1 = failed the base, 2 = failed the dry-up, 3 = failed the breakout, 4 = breakout.
STAGE = {r: 1 for r in REASONS[1:11]} | {"volume_not_lower": 2, "no_quiet_day": 2, "no_close_above_pivot": 3,
                                          "pivot_already_crossed": 3, "breakout_volume_low": 3, "breakout": 4}


@dataclass(frozen=True)
class Contraction:
    high_i: int
    high: float
    low_i: int
    low: float

    @property
    def depth(self) -> float:
        return 1.0 - self.low / self.high


@dataclass(frozen=True)
class Found:
    day: int                          # breakout session index
    contractions: tuple[Contraction, ...]
    swings: tuple[tuple[int, bool, float], ...]  # (index, is_high, price): the alternating swings known at the scan

    @property
    def pivot(self) -> float:
        return self.contractions[-1].high

    @property
    def stop(self) -> float:
        return self.contractions[-1].low


def swing_points(high: np.ndarray, low: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """A swing high is above the k highs before it and not below the k after it (so equal highs keep the first one);
    swing lows mirror that. The first and last k sessions cannot be swings."""
    n = len(high)
    sh, sl = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    if n < 2 * k + 1:
        return sh, sl
    hw, lw = sliding_window_view(high, 2 * k + 1), sliding_window_view(low, 2 * k + 1)
    mid = slice(k, n - k)
    sh[mid] = (high[mid] > hw[:, :k].max(axis=1)) & (high[mid] >= hw[:, k + 1:].max(axis=1))
    sl[mid] = (low[mid] < lw[:, :k].min(axis=1)) & (low[mid] <= lw[:, k + 1:].min(axis=1))
    return sh, sl


class _Alternating:
    """Swings in the order they become known. Two highs in a row keep the higher one; two lows keep the lower."""

    def __init__(self) -> None:
        self.t: list[int] = []
        self.is_high: list[bool] = []
        self.px: list[float] = []

    def push(self, t: int, is_high: bool, px: float) -> None:
        if self.t and self.is_high[-1] == is_high:
            if (px > self.px[-1]) if is_high else (px < self.px[-1]):
                self.t[-1], self.px[-1] = t, px
            return
        self.t.append(t)
        self.is_high.append(is_high)
        self.px.append(px)


def scan(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, vol_avg: np.ndarray,
         candidate: np.ndarray, p: Params) -> tuple[list[tuple[int, str]], list[Found]]:
    """(day, reason) for every candidate day, and the breakouts. Arrays are one symbol's sessions in date order."""
    k, b = p.swings.sessions_each_side, p.base
    sh, sl = swing_points(high, low, k)
    alt = _Alternating()
    reasons: list[tuple[int, str]] = []
    found: list[Found] = []
    for d in range(1, len(high)):
        t = d - 1 - k
        if t >= 0:
            if sl[t]:
                alt.push(t, False, float(low[t]))
            if sh[t]:
                alt.push(t, True, float(high[t]))
        if not candidate[d]:
            continue
        reason, contractions = _base(high, low, alt, d, b)
        if contractions:
            reason = _dry_up(volume, vol_avg, contractions, d, p) or _breakout(close, volume, vol_avg, contractions, d, p)
        reasons.append((d, reason))
        if reason == "breakout":
            start = bisect_left(alt.t, contractions[0].high_i)
            swings = tuple(zip(alt.t[start:], alt.is_high[start:], alt.px[start:], strict=True))
            found.append(Found(d, tuple(contractions), swings))
    return reasons, found


def _base(high: np.ndarray, low: np.ndarray, alt: _Alternating, d: int, b) -> tuple[str, list[Contraction]]:
    first = bisect_left(alt.t, d - b.max_sessions)
    highs = [(alt.t[i], alt.px[i]) for i in range(first, len(alt.t)) if alt.is_high[i]]
    if not highs:
        return "no_swing_high", []
    h0 = max(range(len(highs)), key=lambda i: (highs[i][1], -i))
    t0, px0 = highs[h0]
    if high[t0 + 1:d].max() > px0:
        return "above_base_high", []
    if d - t0 < b.min_sessions:
        return "base_too_short", []
    seq = highs[h0:]
    if len(seq) < b.min_contractions:
        return "too_few_contractions", []
    if len(seq) > b.max_contractions:
        return "too_many_contractions", []
    cs = []
    for i, (t, px) in enumerate(seq):
        end = seq[i + 1][0] if i + 1 < len(seq) else d
        j = t + 1 + int(np.argmin(low[t + 1:end]))
        cs.append(Contraction(t, px, j, float(low[j])))
    if cs[0].depth > b.max_first_depth:
        return "first_too_deep", []
    if any(cs[i + 1].depth >= cs[i].depth for i in range(len(cs) - 1)):
        return "not_contracting", []
    if cs[-1].depth > b.max_last_depth:
        return "last_too_deep", []
    if cs[-1].depth > b.max_last_to_first_depth * cs[0].depth:
        return "not_tightening", []
    if cs[-1].high < b.min_pivot_to_base_high * px0:
        return "pivot_too_low", []
    return "", cs


def _dry_up(volume: np.ndarray, vol_avg: np.ndarray, cs: list[Contraction], d: int, p: Params) -> str:
    last = slice(cs[-1].high_i, d)
    if not volume[last].mean() < volume[cs[0].high_i:cs[1].high_i].mean():
        return "volume_not_lower"
    if not np.any(volume[last] < p.volume.max_quiet_day_to_avg * vol_avg[last]):
        return "no_quiet_day"
    return ""


def _breakout(close: np.ndarray, volume: np.ndarray, vol_avg: np.ndarray, cs: list[Contraction], d: int,
              p: Params) -> str:
    pivot = cs[-1].high
    if not close[d] > pivot:
        return "no_close_above_pivot"
    if close[cs[-1].high_i + 1:d].max() > pivot:  # the breakout is the first close through the pivot
        return "pivot_already_crossed"
    if not volume[d] >= p.breakout.min_volume_to_avg * vol_avg[d]:
        return "breakout_volume_low"
    return "breakout"
