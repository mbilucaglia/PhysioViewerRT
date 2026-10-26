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


class SmoothViewportClock:
    """Monotone presentation clock slewed toward the newest LSL sample.

    This tracks real source timestamps without reconstructing sample times.
    Short-lived GUI scheduling jitter changes the clock's speed slightly
    instead of making the time axis jump forwards or backwards.
    """

    def __init__(self, presentation_delay=0.):
        self.presentation_delay = float(presentation_delay)
        self.reset()

    def reset(self):
        self.head = None
        self.latest_sample = None
        self.received_at = None
        self.frame_at = None

    def observe(self, sample_time, received_at):
        sample_time = float(sample_time)
        received_at = float(received_at)
        if not np.isfinite(sample_time) or not np.isfinite(received_at):
            return
        if self.latest_sample is None or sample_time > self.latest_sample:
            self.latest_sample = sample_time
            self.received_at = received_at
            if self.head is None:
                self.head = sample_time - self.presentation_delay
                self.frame_at = received_at

    def advance(self, now):
        if self.head is None:
            return None
        now = float(now)
        dt = max(0., min(now - self.frame_at, .1))
        self.frame_at = now
        # Consume each source's own real presentation buffer between arrivals.
        # The target controls speed, not a hard stop after a late-block phase
        # correction. Only the latest acquired sample may stop the clock.
        target = min(self.latest_sample,
                     self.latest_sample-self.presentation_delay
                     +max(now-self.received_at,0.))
        distance = target-self.head
        speed = max(0.,min(1.5,1.+distance*3.))
        self.head = min(self.latest_sample,self.head+dt*speed)
        return self.head
