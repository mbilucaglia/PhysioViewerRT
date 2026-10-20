"""Emotional Index (EI) with *within-signal* HR / SCL standardization.

Stage 1: z-score HR and SCL using statistics of the signal being analyzed.
For BSL, use the full 60-s recording; for live monitoring, a causal 60-s
rolling history (no baseline values enter stage 1).
Stage 2: optional transformation of the resulting EI using the EI
distribution saved from BSL. See calibration.normalize().
"""
from collections import deque
import math
import numpy as np

ROLLING_SECONDS = 60.0
MIN_VALID_SAMPLES = 30
MIN_COVERAGE_SECONDS = 55.0


def emotional_index_z(hr_z, gsr_z):
    """Compute angular EI from *already standardized* HR and GSR.

    Keep the convention used previously in PhysioViewerRT; do not treat
    standardized EI as a direct measurement of affect.
    """
    if hr_z is None or gsr_z is None:
        return None
    h, g = float(hr_z), float(gsr_z)
    if not np.isfinite(h) or not np.isfinite(g) or math.hypot(h, g) < 1e-9:
        return None
    theta = math.atan2(h, g)
    if theta < 0:
        beta = abs(theta) + math.pi / 2
    elif theta <= math.pi / 2:
        beta = math.pi / 2 - theta
    else:
        beta = 5 * math.pi / 2 - theta
    return float(np.clip(1.0 - beta / math.pi, -1.0, 1.0))


def standardize_pair(hr, scl):
    """Full-recording z-score for BSL; preserve missing/invalid slots.

    The two arrays must represent the SAME 0.5-second chronological slots.
    Returns HRz, SCLz arrays, with NaNs at rejected positions.
    """
    hr, scl = np.asarray(hr, dtype=float), np.asarray(scl, dtype=float)
    if hr.ndim != 1 or scl.ndim != 1 or hr.shape != scl.shape:
        raise ValueError('HR and SCL metric arrays must share chronological slots')

    def zscore(values):
        finite = np.isfinite(values)
        if finite.sum() < MIN_VALID_SAMPLES:
            return np.full_like(values, np.nan)
        sigma = float(np.std(values[finite], ddof=1))
        if not np.isfinite(sigma) or sigma < 1e-12:
            return np.full_like(values, np.nan)
        out = np.full_like(values, np.nan)
        out[finite] = (values[finite] - np.mean(values[finite])) / sigma
        return out

    return zscore(hr), zscore(scl)


def baseline_ei(hr_series, scl_series):
    """EI computed from z-scored BSL signals, using aligned 0.5-s slots."""
    h, g = standardize_pair(hr_series, scl_series)
    return np.array(
        [emotional_index_z(hi, gi) if np.isfinite(hi) and np.isfinite(gi)
         else np.nan for hi, gi in zip(h, g)],
        dtype=float
    )


class RollingEmotionalIndex:
    """Streaming 60-second causal z-scoring with freshness/quality gating.

    update() accepts contemporaneous *metric* samples and their monotonic
    acquisition times. Call at the metric cadence (nominally 0.5 s).
    Missing values are discarded, never replaced by old HR/SCL.
    """
    def __init__(self, seconds=ROLLING_SECONDS):
        self.seconds = float(seconds)
        self.history = {'HR': deque(), 'SCL': deque()}
        self.latest = {}

    def update(self, kind, value, timestamp):
        name = {'PPG': 'HR', 'EDA': 'SCL'}.get(kind)
        if name is None:
            return
        t = float(timestamp)
        if value is not None and np.isfinite(value):
            pair = (t, float(value))
            self.history[name].append(pair)
            self.latest[name] = pair
        self._trim(t)

    def _trim(self, now):
        cutoff = now - self.seconds
        for stream in self.history.values():
            while stream and stream[0][0] < cutoff:
                stream.popleft()

    def value(self, now):
        now = float(now)
        self._trim(now)
        if not all(name in self.latest for name in ('HR', 'SCL')):
            return None
        if any(now - self.latest[k][0] > 1.0 for k in ('HR', 'SCL')):
            return None
        # Pair updates must be close in time; streams need not be simultaneous.
        if abs(self.latest['HR'][0] - self.latest['SCL'][0]) > 1.0:
            return None
        z = {}
        for key, history in self.history.items():
            if (len(history) < MIN_VALID_SAMPLES or
                    history[-1][0] - history[0][0] < MIN_COVERAGE_SECONDS):
                return None
            data = np.asarray([v for _, v in history], dtype=float)
            sigma = float(np.std(data, ddof=1))
            if not np.isfinite(sigma) or sigma < 1e-12:
                return None
            z[key] = float((self.latest[key][1] - np.mean(data)) / sigma)
        return emotional_index_z(z['HR'], z['SCL'])
