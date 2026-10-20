"""Emotional Index based on baseline-z-scored HR and EDA SCL.

The EI implementation uses quadrant-aware angle handling (Vecchiato/Babiloni
convention). EI itself is then optionally normalized against its own BSL
distribution for visualization. A BSL must have valid HR and SCL reference
statistics before EI can be computed.
"""
import numpy as np


def emotional_index(hr, scl, hr_reference, scl_reference):
    """Return EI in [-1, 1] or None for invalid data/references.

    theta=atan2(HRz, SCLz) and a quadrant adjustment determine beta,
    EI=1-beta/pi. Origin is undefined; never invent a value.
    """
    if hr is None or scl is None or not hr_reference or not scl_reference:
        return None
    try:
        h_std = float(hr_reference['sigma'])
        s_std = float(scl_reference['sigma'])
        if h_std <= 1e-12 or s_std <= 1e-12:
            return None
        hz = (float(hr) - float(hr_reference['mu'])) / h_std
        sz = (float(scl) - float(scl_reference['mu'])) / s_std
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    if not np.isfinite(hz) or not np.isfinite(sz) or np.hypot(hz, sz) < 1e-9:
        return None
    theta = float(np.arctan2(hz, sz))
    if theta < 0:
        beta = abs(theta) + np.pi / 2
    elif theta <= np.pi / 2:
        beta = np.pi / 2 - theta
    else:
        beta = 5 * np.pi / 2 - theta
    value = 1 - beta / np.pi
    return float(np.clip(value, -1.0, 1.0))
