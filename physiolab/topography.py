"""Display-only EEG maps. No acquisition, calibration or Qt state is modified."""
from dataclasses import dataclass
from functools import lru_cache
import re

import numpy as np
from scipy.signal import welch
from scipy.spatial import Delaunay
from .eeg_montage import POSITIONS, ALIASES, unproject_positions
from .spherical_spline import spherical_spline_matrix


BANDS = {'Delta': (1., 4.), 'Theta': (4., 8.), 'Alpha': (8., 13.),
         'Beta': (13., 30.), 'Gamma': (30., 45.)}
GRID_SIZE = 128
_GRID_AXIS = (np.arange(GRID_SIZE, dtype=float) + .5)*2/GRID_SIZE - 1.
_GRID_POINTS = np.stack(np.meshgrid(_GRID_AXIS, _GRID_AXIS), axis=-1).reshape(-1, 2)
SCALP_MASK = np.sum(_GRID_POINTS ** 2, axis=1) <= 1.
_GRID_POINTS.setflags(write=False)
SCALP_MASK.setflags(write=False)


def electrode_key(label):
    label = re.sub(r'^eeg\s+', '', str(label).strip(), flags=re.I).lower()
    # Only recognized reference suffixes; bipolar pairs must not become sensors.
    label = re.sub(r'[-_](ref|le|re|avg)$', '', label)
    return ALIASES.get(label, label)


def band_limits(band, iaf=None):
    if band == 'Unfiltered':
        return None
    if band == 'Alpha' and iaf is not None and np.isfinite(iaf) and 6. <= iaf <= 16.:
        return (float(iaf) - 2., float(iaf) + 2.)
    return BANDS[band]


@dataclass(frozen=True)
class TopographySettings:
    band: str = 'Alpha'
    source: str = 'processed'
    window: float = 2.
    overlap: float = .5
    persistence: float = .15
    use_iaf: bool = True
    extrapolate: bool = True

    def __post_init__(self):
        if self.band not in (*BANDS, 'Unfiltered') or self.source not in ('raw', 'processed'):
            raise ValueError('Unknown topography mode')
        if not (.25 <= self.window <= 10. and 0. <= self.overlap <= .95
                and 0. <= self.persistence <= 2.):
            raise ValueError('Invalid topography window, overlap or persistence')

    @property
    def hop(self):
        return self.window * (1. - self.overlap)


@lru_cache(maxsize=2)
def interpolation_weights(positions):
    """Full-grid spherical-spline weights and the electrode-coverage mask."""
    xy = np.asarray(positions, dtype=float)
    weights = spherical_spline_matrix(unproject_positions(xy),
                                      unproject_positions(_GRID_POINTS), dtype=np.float32)
    mask = (Delaunay(xy).find_simplex(_GRID_POINTS) >= 0) & SCALP_MASK
    return weights, mask


def calculate_topography(chunks, end, settings, scales=1., unit='a.u.', iaf=None):
    """Pure calculation from immutable history blocks, on a background worker.

    Band power is Hann-windowed PSD integrated over [low, high). Unfiltered is
    the latest signed raw voltage, optionally exponentially weighted over the
    preceding 5 time constants (99.3% mass); persistence uses source timestamps.
    """
    if not chunks:
        raise ValueError('Waiting for EEG samples')
    names, fs = chunks[-1][3:5]
    retained = max(settings.window, 5. * settings.persistence if settings.band == 'Unfiltered' else 0.)
    blocks = [c for c in chunks if c[0][-1] >= end - retained and c[0][0] <= end]
    if not blocks:
        raise ValueError('No EEG samples at this time')
    if any(c[3] != names or c[4] != fs for c in blocks):
        raise ValueError('EEG channel configuration changed; waiting for a new window')
    if not np.isfinite(fs) or fs <= 0:
        raise ValueError('EEG requires a positive sampling rate')
    t = np.concatenate([c[0] for c in blocks])
    source = 1 if settings.band == 'Unfiltered' or settings.source == 'raw' else 2
    x = np.concatenate([c[source] for c in blocks])
    keep = (t <= end + 1e-9) & (t > end - retained - 1e-9)
    t, x = t[keep], x[keep]
    if not len(t):
        raise ValueError('Waiting for EEG samples')
    # Gaps cannot be interpolated into spectra or carried across persistence.
    gaps = np.flatnonzero(np.diff(t) > 2.5 / fs)
    if len(gaps):
        t, x = t[gaps[-1] + 1:], x[gaps[-1] + 1:]
    if end - t[-1] > 2.5 / fs:
        raise ValueError('EEG gap at the selected time')
    window = t > end - settings.window - 1e-9
    if np.count_nonzero(window) < max(4, int(np.floor(settings.window * fs)) - 1):
        raise ValueError(f'Waiting for {settings.window:g} s of continuous EEG')
    x = x * np.asarray(scales)
    indices, labels, positions, excluded = [], [], [], []
    for i, label in enumerate(names):
        position = POSITIONS.get(electrode_key(label))
        if position is None or position in positions or not np.isfinite(x[:, i]).all():
            excluded.append(str(label))
        else:
            indices.append(i)
            labels.append(str(label))
            positions.append(position)
    if len(indices) < 3 or np.linalg.matrix_rank(np.asarray(positions) - np.mean(positions, axis=0)) < 2:
        raise ValueError('Need ≥3 non-collinear EEG electrodes with recognized labels; '
                         'excluded: ' + (', '.join(excluded) or 'none'))
    x = x[:, indices]
    limits = band_limits(settings.band, iaf if settings.use_iaf else None)
    if limits is None:
        if settings.persistence:
            weights = np.exp((t - t[-1]) / settings.persistence)
            values = weights @ x / weights.sum()
        else:
            values = x[-1]
        quantity = f'Signed voltage ({unit})'
    else:
        low, high = limits
        if high > fs / 2.:
            raise ValueError(f'{settings.band} requires sampling ≥{2*high:g} Hz')
        f, psd = welch(x[window], fs=fs, nperseg=np.count_nonzero(window),
                       window='hann', detrend='constant', axis=0)
        bins = (f >= low) & (f < high)
        if np.count_nonzero(bins) < 2:
            raise ValueError('Window too short for this band; increase Window')
        values = psd[bins].sum(axis=0) * (f[1] - f[0])
        quantity = f'{settings.band} {low:g}–{high:g} Hz power ({unit}²)'
    weights, coverage_mask = interpolation_weights(tuple(positions))
    if limits is None:
        average = values.mean()
        grid = average + weights @ (values-average)
    elif values.max() > 0:
        # Spline log power, then restore original units: smooth positive fields
        # without hard zero clipping or pretending power is a signed potential.
        log_values = np.log(np.maximum(values, max(values.max()*1e-12, np.finfo(float).tiny)))
        average = log_values.mean()
        with np.errstate(over='ignore'):
            grid = np.exp(average + weights @ (log_values-average))
    else:
        grid = np.zeros(len(_GRID_POINTS))
    mask = SCALP_MASK if settings.extrapolate else coverage_mask
    if not np.isfinite(grid[mask]).all():
        raise ValueError('Spherical-spline field is unstable for this electrode coverage')
    if limits is None:
        magnitude = max(float(np.max(np.abs(grid[mask]))), float(np.max(np.abs(values))), 1e-12)
        levels = (-magnitude, magnitude)
    else:
        levels = (0., max(float(grid[mask].max()), float(values.max()), 1e-24))
    grid[~mask] = np.nan
    extrapolated = mask & ~coverage_mask
    return dict(grid=grid.reshape(GRID_SIZE, GRID_SIZE), values=values, positions=positions,
                extrapolated=extrapolated.reshape(GRID_SIZE, GRID_SIZE),
                labels=labels, excluded=excluded, levels=levels, quantity=quantity,
                end=float(t[-1]), band=settings.band)
