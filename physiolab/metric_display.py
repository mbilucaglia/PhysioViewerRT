"""Display-only metric smoothing and gap-aware interpolation.

Metric observations remain at their original cadence (~0.5 s). Rendered
interpolation does not increase the physiological sampling resolution.
"""
import numpy as np
from scipy.interpolate import PchipInterpolator, CubicSpline



def monotonic_display_samples(times, values):
    """Keep time order and the latest value for a repeated timestamp.

    GUI event scheduling can generate repeated metric timestamps. Ignore
    backwards/non-finite times rather than crashing PCHIP/cubic rendering.
    Original metric storage and calibration data remain untouched.
    """
    t = np.asarray(times, dtype=float)
    v = np.asarray(values, dtype=float)
    if t.ndim != 1 or v.ndim != 1 or t.shape != v.shape:
        raise ValueError('Display timestamps and values must be matching vectors')
    indices = []
    for index, stamp in enumerate(t):
        if not np.isfinite(stamp):
            continue
        if not indices or stamp > t[indices[-1]]:
            indices.append(index)
        elif stamp == t[indices[-1]]:
            indices[-1] = index
    return t[indices], v[indices]


def prepare_metric_curve(times, values, smoothing='none', seconds=2.0,
                         interpolation='pchip', display_hz=20.0,
                         max_gap=1.1):
    """Return interpolated (x,y) and actual-observation (x,y) arrays.

    Invalid observations and gaps > max_gap split the curve. Smoothing is
    causal and confined to contiguous valid segments. Interpolation uses
    observed points only (never extrapolates). Output groups have NaN
    separators so pyqtgraph cannot bridge unavailable data.
    """
    x = np.asarray(times, dtype=float)
    y = np.asarray(values, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.shape != y.shape:
        raise ValueError('Metric timestamps and values must be matching vectors')
    if smoothing not in ('none', 'mean', 'ema', 'median'):
        raise ValueError('Unknown metric smoothing method')
    if interpolation not in ('none', 'linear', 'pchip', 'cubic'):
        raise ValueError('Unknown interpolation method')
    if seconds <= 0 or display_hz <= 0 or max_gap <= 0:
        raise ValueError('Durations and interpolation rate must be positive')
    x, y = monotonic_display_samples(x, y)
    if not len(x):
        empty = np.empty(0, dtype=float)
        return empty, empty, empty, empty

    valid = np.isfinite(y)
    breaks = np.where(
        (~valid[1:]) | (~valid[:-1]) | (np.diff(x) > max_gap)
    )[0] + 1
    curve_x, curve_y, point_x, point_y = [], [], [], []
    begin = 0
    for end in list(breaks) + [len(x)]:
        tx, vy = x[begin:end], y[begin:end]
        begin = end
        if not len(tx) or not np.all(np.isfinite(vy)):
            continue
        smooth = np.asarray(vy, dtype=float).copy()
        if smoothing == 'mean' or smoothing == 'median':
            for i in range(len(tx)):
                lo = np.searchsorted(tx, tx[i] - seconds, side='left')
                history = vy[lo:i + 1]
                smooth[i] = (np.mean(history) if smoothing == 'mean'
                             else np.median(history))
        elif smoothing == 'ema':
            for i in range(1, len(tx)):
                alpha = 1. - np.exp(-np.log(2) * (tx[i] - tx[i-1]) / seconds)
                smooth[i] = alpha * vy[i] + (1 - alpha) * smooth[i - 1]

        point_x.extend(tx.tolist())
        point_y.extend(vy.tolist())
        if interpolation == 'none':
            ix, iy = tx, smooth
        elif len(tx) < 2:
            ix, iy = tx, smooth
        else:
            # 20 render points per second, not 20 new observations.
            n = max(2, int(np.ceil((tx[-1] - tx[0]) * display_hz)) + 1)
            ix = np.linspace(tx[0], tx[-1], n)
            if interpolation == 'linear' or len(tx) < 3:
                iy = np.interp(ix, tx, smooth)
            elif interpolation == 'pchip':
                iy = PchipInterpolator(tx, smooth)(ix)
            else:
                iy = CubicSpline(tx, smooth, bc_type='natural')(ix)

        if curve_x:
            curve_x.append(np.nan)
            curve_y.append(np.nan)
        curve_x.extend(np.asarray(ix).tolist())
        curve_y.extend(np.asarray(iy).tolist())
    return tuple(np.asarray(v, dtype=float) for v in
                 (curve_x, curve_y, point_x, point_y))
