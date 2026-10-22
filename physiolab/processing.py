"""Stateful sample filtering and metric cadence; algorithms live in pure modules."""
import numpy as np
from scipy.signal import sosfilt
from .signal_buffer import SampleRing

# Compatibility exports remain available from the original processing module.
from .processing_filters import FILTER_PRESETS, validate_preprocessing, build_filter
from .physiological_metrics import (DEFAULT_IAF_HZ, ALPHA_HALF_WIDTH_HZ,
                                    METRIC_CALCULATORS)

PROCESSING_HISTORY_SECONDS = 20.
METRIC_HOP_SECONDS = .5
METRIC_STARTUP_SECONDS = 1.


class Processor:
    def __init__(self, kind, fs, channels, names, iaf_hz=DEFAULT_IAF_HZ, preprocessing=None):
        self.kind, self.fs, self.channels, self.names = kind, float(fs), channels, names
        if not np.isfinite(self.fs) or self.fs <= 0:
            raise ValueError('Sampling rate must be finite and positive')
        if channels < 1 or len(names) != channels:
            raise ValueError('Channel count and labels must match')
        self.iaf_hz = float(iaf_hz)
        config = validate_preprocessing(kind, **(preprocessing or {}))
        self.preprocessing = config
        self.sos, self.notch_frequencies = build_filter(kind, self.fs, config)
        self.zi = np.zeros((self.sos.shape[0], 2, channels)) if self.sos is not None else None
        calculator = METRIC_CALCULATORS.get(kind)
        history_seconds = max(PROCESSING_HISTORY_SECONDS,
                              calculator.window_seconds if calculator else 0.)
        self.max_samples = max(round(self.fs * history_seconds), int(self.fs) + 2)
        self._raw_history = SampleRing(self.max_samples, channels)
        self._filtered_history = SampleRing(self.max_samples, channels)
        self.last_filtered_chunk = np.empty((0, channels))
        self.since_metric = 0
        self.last_metric = {}

    def push(self, chunk):
        x = np.asarray(chunk, dtype=float).reshape(-1, self.channels)
        if not len(x):
            return None
        if not np.isfinite(x).all():
            raise ValueError('Signal contains NaN or infinite samples; check the source')
        if self.sos is not None:
            y, self.zi = sosfilt(self.sos, x, axis=0, zi=self.zi)
        else:
            y = x.copy()
        self._raw_history.append(x)
        self._filtered_history.append(y)
        self.last_filtered_chunk = y
        self.since_metric += len(x)
        hop = max(1, round(self.fs * METRIC_HOP_SECONDS))
        if self.since_metric >= hop and len(self._filtered_history) >= round(self.fs * METRIC_STARTUP_SECONDS):
            self.since_metric %= hop
            self.last_metric = self.metrics()
            return self.last_metric
        return None

    @property
    def raw(self):
        return self._raw_history.tail(self.max_samples)

    @property
    def filtered(self):
        return self._filtered_history.tail(self.max_samples)

    def metrics(self):
        calculator = METRIC_CALCULATORS.get(self.kind)
        if calculator is None:
            return {}
        window = self._filtered_history.tail(round(self.fs * calculator.window_seconds))
        return calculator.calculate(window, self.fs, self.names, self.iaf_hz)
