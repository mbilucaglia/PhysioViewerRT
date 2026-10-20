"""Emotional Index using BSL-fixed HR/SCL mean and standard deviation.

Stage 1: z-score live HR and SCL using the fixed HR/SCL statistics computed
during BSL; BSL EI uses HR/SCL z-scored within that same baseline recording.
Stage 2: apply the user's optional display transform to EI using the
BSL EI reference distribution (calibration.normalize).
"""
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


def emotional_index_from_bsl(hr, scl, hr_reference, scl_reference):
    """Calculate EI using HR/SCL z-scores relative to BSL statistics.

    Missing/invalid HR, SCL or reference variance => None.
    """
    if hr is None or scl is None or not hr_reference or not scl_reference:
        return None
    try:
        hr = float(hr)
        scl = float(scl)
        mh = float(hr_reference['mu'])
        sh = float(hr_reference['sigma'])
        mg = float(scl_reference['mu'])
        sg = float(scl_reference['sigma'])
    except (TypeError, ValueError, KeyError):
        return None
    if not all(np.isfinite(v) for v in (hr, scl, mh, sh, mg, sg)):
        return None
    if sh <= 1e-12 or sg <= 1e-12:
        return None
    return emotional_index_z((hr - mh) / sh, (scl - mg) / sg)


class BaselineEmotionalIndex:
    """Combine fresh HR/SCL metric values using fixed BSL statistics.

    Only validity/freshness gating remains: no 60-second live history.
    """

    def __init__(self, hr_reference=None, scl_reference=None, max_age=1.0):
        self.hr_reference = hr_reference
        self.scl_reference = scl_reference
        self.max_age = float(max_age)
        self.latest = {}

    def set_references(self, hr_reference, scl_reference):
        self.hr_reference = hr_reference
        self.scl_reference = scl_reference

    def update(self, kind, value, timestamp):
        name = {'PPG': 'HR', 'EDA': 'SCL'}.get(kind)
        if name is None:
            return
        if value is None or not np.isfinite(value):
            self.latest.pop(name, None)
        else:
            self.latest[name] = (float(timestamp), float(value))

    def value(self, now):
        if not all(k in self.latest for k in ('HR', 'SCL')):
            return None
        if any(now - self.latest[k][0] > self.max_age for k in ('HR', 'SCL')):
            return None
        if abs(self.latest['HR'][0] - self.latest['SCL'][0]) > self.max_age:
            return None
        return emotional_index_from_bsl(
            self.latest['HR'][1], self.latest['SCL'][1],
            self.hr_reference, self.scl_reference
        )
