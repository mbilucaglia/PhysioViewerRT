"""Emotional Index using BSL-fixed HR/SCL mean and standard deviation.

Stage 1: z-score live HR and SCL using the fixed HR/SCL statistics computed
during BSL; BSL EI uses HR/SCL z-scored within that same baseline recording.
Stage 2: apply the user's optional display transform to EI using the
BSL EI reference distribution (calibration.normalize).
"""
import math
import numpy as np

MIN_VALID_SAMPLES = 30


def emotional_index_z(hr_z, gsr_z):
    """Vecchiato EI_matrix angular formula for z-scored HR and GSR.

    MATLAB reference:
        theta = atan2(SCL, HR)
        beta = pi/2 - theta
        if SCL >= 0 and HR <= 0: beta = 2.5*pi - theta
        EI = 1 - beta/pi

    HR is horizontal, GSR/SCL vertical. The source MATLAB returns NaN
    for an all-zero HR vector. A scalar HR_z of zero is thus treated
    as unavailable, consistent with a length-one MATLAB input.
    Do not clip the calculated output; preserve the supplied formula.
    """
    if hr_z is None or gsr_z is None:
        return None
    try:
        h, g = float(hr_z), float(gsr_z)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(h) or not np.isfinite(g) or h == 0.:
        return None
    theta = math.atan2(g, h)
    beta = 2.5 * math.pi - theta if g >= 0. and h <= 0. else (
        math.pi / 2 - theta
    )
    return float(1. - beta / math.pi)



def ei_matrix(scl_z, hr_z):
    """MATLAB EI_matrix equivalent for an epoch of already-z-scored data.

    HR is the horizontal axis, SCL the vertical axis. The MATLAB guard
    applies to the ENTIRE HR epoch, not to each individual HR sample.
    Missing sample pairs remain NaN in the result.
    """
    scl = np.asarray(scl_z, dtype=float)
    hr = np.asarray(hr_z, dtype=float)
    if scl.shape != hr.shape:
        raise ValueError('HR and SCL epochs must have identical shapes')
    if not np.any(np.isfinite(hr) & (hr != 0)):
        return np.full(hr.shape, np.nan, dtype=float)
    theta = np.arctan2(scl, hr)
    beta = np.pi / 2 - theta
    beta = np.where((scl >= 0) & (hr <= 0), 2.5 * np.pi - theta, beta)
    ei = 1 - beta / np.pi
    return np.where(np.isfinite(hr) & np.isfinite(scl), ei, np.nan)


def ei_epochs(scl_epochs, hr_epochs, scl_reference, hr_reference):
    """MATLAB normalize_struct(zscore) -> EI_matrix for each epoch.

    The normalization factors are fixed BSL statistics. HR/SCL epochs
    have identical shapes/timing within each pair. No live rolling
    normalization or separate z-scoring within epochs occurs.
    """
    if len(scl_epochs) != len(hr_epochs):
        raise ValueError('HR and SCL must have matching epoch counts')
    if not scl_reference or not hr_reference:
        raise ValueError('Valid BSL HR and SCL references are required')
    try:
        mean_h, sigma_h = float(hr_reference['mu']), float(hr_reference['sigma'])
        mean_g, sigma_g = float(scl_reference['mu']), float(scl_reference['sigma'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Invalid BSL reference statistics') from exc
    if (not all(np.isfinite(x) for x in (mean_h, sigma_h, mean_g, sigma_g))
            or sigma_h <= 1e-12 or sigma_g <= 1e-12):
        raise ValueError('BSL standard deviations must be positive and finite')
    output = []
    for scl, hr in zip(scl_epochs, hr_epochs):
        scl = np.asarray(scl, dtype=float)
        hr = np.asarray(hr, dtype=float)
        output.append(ei_matrix((scl - mean_g) / sigma_g,
                                (hr - mean_h) / sigma_h))
    return output


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
    return ei_matrix(g, h)


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
