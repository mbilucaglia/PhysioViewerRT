"""Prepare raw waveforms away from Qt's GUI thread.

Snapshots hold references to immutable LSL chunks. All cropping,
decimation and per-channel normalization runs in the render thread.
No pyqtgraph or Qt widget is accessed by these functions.
"""
import numpy as np


def prepare_raw_window(chunks, left, right, origin, reference=None,
                       max_points=2500, max_channels=8):
    """Return time and display-scaled traces for a raw modality.

    A result is (time, raw_traces, filtered_traces, centers, scales,
    labels). Cropping, channel limiting and decimation all happen before
    concatenation, so long/high-channel histories do not create large
    temporary arrays merely to draw a small screen-sized frame.
    """
    if not chunks or origin is None or right <= left:
        return None
    if max_points < 1 or max_channels < 1:
        raise ValueError('max_points and max_channels must be positive')

    t_min, t_max = origin + left, origin + right
    selected = []
    total_samples = 0
    for item in reversed(chunks):
        stamps = np.asarray(item[0], dtype=float)
        if not len(stamps):
            continue
        if stamps[-1] < t_min:
            break
        if stamps[0] > t_max:
            continue
        lo = int(np.searchsorted(stamps, t_min, side='left'))
        hi = int(np.searchsorted(stamps, t_max, side='right'))
        if hi > lo:
            selected.append((item, lo, hi))
            total_samples += hi - lo
    if not selected:
        return None

    selected.reverse()
    latest = selected[-1][0]
    n = min(np.asarray(latest[1]).shape[1], int(max_channels))
    if n < 1:
        return None

    fs = float(latest[4])
    if reference is None and total_samples < max(8, round(fs * .75)):
        # Do not establish display scale from just a few startup samples.
        # Use the pre-decimation sample count so high-rate streams can still
        # initialize when the screen point budget is lower than 0.75 * fs.
        return None

    stride = max(1, int(np.ceil(total_samples / float(max_points))))
    times, raws, filters = [], [], []
    consumed = 0
    for (stamps, raw, processed, _, _), lo, hi in selected:
        count = hi - lo
        first = (-consumed) % stride
        if first < count:
            sample_slice = slice(lo + first, hi, stride)
            times.append(np.asarray(stamps)[sample_slice])
            # Limit channels before any concatenation. This is the important
            # path for 32/64-channel EEG with multi-minute timebases.
            raws.append(np.asarray(raw)[sample_slice, :n])
            filters.append(np.asarray(processed)[sample_slice, :n])
        consumed += count

    if not times:
        return None
    t = np.concatenate(times)
    x = np.concatenate(raws, axis=0)
    y = np.concatenate(filters, axis=0)

    if reference is None:
        centers = np.median(x, axis=0)
        scales = np.std(x, axis=0)
        scales = np.where(np.isfinite(scales) & (scales > 1e-12),
                          scales, 1.0)
    else:
        centers, scales = reference
        if len(centers) != n or len(scales) != n:
            raise ValueError('Display scale differs from channel count')

    offsets = 6 * np.arange(n, dtype=float)
    return (t-origin, (x-centers)/scales+offsets,
            (y-centers)/scales+offsets, centers, scales,
            tuple(latest[3][:n]))
