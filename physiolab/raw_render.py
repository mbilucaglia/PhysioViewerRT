"""Prepare raw waveforms away from Qt's GUI thread.

Snapshots hold references to immutable LSL chunks. All cropping,
decimation and per-channel normalization runs in the render thread.
No pyqtgraph or Qt widget is accessed by these functions.
"""
import numpy as np
from .raw_timing import visible_chunk


def prepare_raw_window(chunks, left, right, origin, reference=None,
                       max_points=2500, max_channels=8):
    """Return time and display-scaled traces for a raw modality.

    A result is (time, raw_traces, filtered_traces, centers, scales,
    labels). The output has at most max_points samples and max_channels
    channels. Fixed scaling is reused when supplied.
    """
    if not chunks or origin is None or right <= left:
        return None
    t_min, t_max = origin + left, origin + right
    selected = []
    for item in reversed(chunks):
        stamps = item[0]
        if stamps[-1] < t_min:
            break
        if stamps[0] <= t_max:
            selected.append(item)
    times, raws, filters = [], [], []
    for stamps, raw, processed, _, _ in reversed(selected):
        ts, x, y = visible_chunk(stamps, raw, processed, t_min, t_max)
        if len(ts):
            times.append(ts)
            raws.append(x)
            filters.append(y)
    if not times:
        return None
    t = np.concatenate(times)
    x = np.concatenate(raws)
    y = np.concatenate(filters)
    # Anchor decimation to the stream's sample clock rather than the first
    # sample in the moving viewport. The previous t[::stride] scheme changed
    # which historical points were retained whenever the viewport moved by
    # one sample, making the *already drawn* sweep visibly shimmer.
    fs = float(chunks[-1][4])
    if not np.isfinite(fs) or fs <= 0:
        fs = max(1., len(t) / max(right-left, 1e-6))
    stride = max(1, int(np.ceil(fs * (right-left) / max_points)))
    if stride > 1:
        # Using origin-relative nominal sample indices fixes the phase across
        # frames without requiring sample-index counters in the LSL reader.
        index = np.rint((t - origin) * fs).astype(np.int64)
        keep = index % stride == 0
        t, x, y = t[keep], x[keep], y[keep]
        if not len(t):
            return None
    n = min(x.shape[1], max_channels)
    x, y = x[:, :n], y[:, :n]
    if reference is None:
        # Do not establish display scale from just a few startup samples.
        fs = float(chunks[-1][4])
        if len(x) < max(8, round(fs * .75)):
            return None
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
            tuple(chunks[-1][3][:n]))
