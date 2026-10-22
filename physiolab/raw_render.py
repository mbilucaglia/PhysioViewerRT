"""Prepare raw waveforms away from Qt's GUI thread.

Snapshots hold references to immutable LSL chunks. All cropping,
decimation and per-channel normalization runs in the render thread.
No pyqtgraph or Qt widget is accessed by these functions.
"""
import numpy as np
from .raw_timing import visible_chunk


def prepare_raw_window(chunks, left, right, origin, reference=None,
                       max_points=2500, max_channels=8,
                       decimation_span=None):
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
    if not selected:
        return None
    if max_channels < 1 or max_points < 1:
        raise ValueError('Positive channel and point budgets required')
    n = min(selected[-1][1].shape[1], int(max_channels))
    times, raws, filters = [], [], []
    for stamps, raw, processed, _, _ in reversed(selected):
        # Narrow to displayed channels before copying/concatenating samples.
        # EEG acquisition can retain 64+ channels when only 8 are shown.
        ts, x, y = visible_chunk(
            stamps, raw[:, :n], processed[:, :n], t_min, t_max)
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
    # For incremental sweeps the cropped tail may be only 100ms, but
    # its fixed decimation must match the original full sweep window.
    decimation_seconds = (
        float(decimation_span) if decimation_span is not None else right-left)
    if decimation_seconds <= 0:
        raise ValueError('Decimation window must be positive')
    stride = max(1, int(np.ceil(fs * decimation_seconds / max_points)))
    if stride > 1:
        # Using origin-relative nominal sample indices fixes the phase across
        # frames without requiring sample-index counters in the LSL reader.
        index = np.rint((t - origin) * fs).astype(np.int64)
        keep = index % stride == 0
        # During initial connection a short chunk may contain no sample
        # on the global decimation grid. Render that chunk immediately
        # rather than waiting for the next grid-aligned timestamp.
        # Once at least two aligned points exist, resume the stable phase.
        if np.count_nonzero(keep) >= 2:
            t, x, y = t[keep], x[keep], y[keep]
        elif len(t) < 2:
            return None
    if reference is None:
        # A waveform needs only two samples. Never impose a 0.75-second
        # holdoff before the first visible trace. Scale is latched by
        # the GUI after this first frame and reused thereafter.
        if len(x) < 2:
            return None
        centers = np.median(x, axis=0)
        scales = np.std(x, axis=0)
        # Avoid extreme gains from near-flat startup samples. The floor
        # is relative to the observed signal level, with an absolute
        # fallback for a zero-valued stream.
        floor = np.maximum(np.max(np.abs(x), axis=0) * 1e-6, 1e-9)
        scales = np.where(np.isfinite(scales), np.maximum(scales, floor), 1.0)
    else:
        centers, scales = reference
        if len(centers) != n or len(scales) != n:
            raise ValueError('Display scale differs from channel count')
    offsets = 6 * np.arange(n, dtype=float)
    return (t-origin, (x-centers)/scales+offsets,
            (y-centers)/scales+offsets, centers, scales,
            tuple(chunks[-1][3][:n]))
