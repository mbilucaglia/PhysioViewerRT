"""Canonical and IAF-derived EEG frequency-band boundaries."""
import numpy as np


IAF_BAND_CONVENTION = 'Borghini et al. (2019), Sensors 19(3), 704, Table 1'
IAF_VALID_RANGE_HZ = (6., 16.)
IAF_BAND_NAMES = ('Delta', 'Theta', 'Alpha', 'Beta', 'Gamma')


def derive_iaf_bands(iaf_hz):
    """Return JSON-safe [low, high] limits from the EYC-calibrated IAF."""
    iaf = float(iaf_hz)
    if not np.isfinite(iaf) or not IAF_VALID_RANGE_HZ[0] <= iaf <= IAF_VALID_RANGE_HZ[1]:
        raise ValueError('IAF must be finite and between 6 and 16 Hz')
    return {
        'Delta': [0., iaf - 6.],
        'Theta': [iaf - 6., iaf - 2.],
        'Alpha': [iaf - 2., iaf + 2.],
        'Beta': [iaf + 2., iaf + 16.],
        'Gamma': [iaf + 16., iaf + 25.],
    }


def validated_iaf_bands(value):
    """Return finite ordered IAF limits or None for absent/legacy metadata."""
    if not isinstance(value, dict) or any(name not in value for name in IAF_BAND_NAMES):
        return None
    result = {}
    for name in IAF_BAND_NAMES:
        limits = value[name]
        if not isinstance(limits, (list, tuple)) or len(limits) != 2:
            return None
        low, high = limits
        if (not isinstance(low, (int, float)) or not isinstance(high, (int, float))
                or not np.isfinite(low) or not np.isfinite(high)
                or low < 0. or high < low):
            return None
        result[name] = (float(low), float(high))
    return result
