"""Timestamp-aligned, monotonic raw LSL samples for waveform rendering.

LSL timestamps, not GUI arrival times, are the source of truth.
"""
import numpy as np


def clean_lsl_chunk(timestamps, raw, filtered, previous_time=None):
    """Drop invalid/duplicate/backwards timestamps, preserving sample pairing.

    A backwards or repeated time is never allowed to produce a backwards
    line segment. No fabricated timestamps or time sorting is performed.
    """
    t = np.asarray(timestamps, dtype=float)
    x = np.asarray(raw, dtype=float)
    y = np.asarray(filtered, dtype=float)
    if t.ndim != 1 or x.ndim != 2 or y.ndim != 2:
        raise ValueError('Expected timestamps vector and 2D signal arrays')
    if len(t) != len(x) or x.shape != y.shape:
        raise ValueError('LSL timestamps and raw/filtered chunks must align')
    if not len(t):
        return t, x, y
    keep = np.zeros(len(t), dtype=bool)
    last = float(previous_time) if previous_time is not None else -np.inf
    for i, instant in enumerate(t):
        if np.isfinite(instant) and instant > last:
            keep[i] = True
            last = instant
    return t[keep], x[keep], y[keep]


def visible_chunk(timestamps, raw, filtered, start, stop):
    """Select samples inside a time viewport using true sample times."""
    t = np.asarray(timestamps, dtype=float)
    lo = int(np.searchsorted(t, start, side='left'))
    hi = int(np.searchsorted(t, stop, side='right'))
    return t[lo:hi], raw[lo:hi], filtered[lo:hi]
