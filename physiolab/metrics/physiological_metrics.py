"""Pure physiological metric calculations; no buffering or UI dependencies.

Each modality declares its required history and calculator in METRIC_CALCULATORS.
These are the existing algorithms, separated from acquisition cadence and state.
"""
from dataclasses import dataclass
import math
from typing import Callable
import numpy as np
from scipy.signal import welch, find_peaks

DEFAULT_IAF_HZ = 10.0
ALPHA_HALF_WIDTH_HZ = 2.0
BETA_BAND_HZ = (13., 30.)
MIN_ALPHA_POWER = 1e-18
FRONTAL_LEFT_LABELS = ('f3', 'fp1')
FRONTAL_RIGHT_LABELS = ('f4', 'fp2')
PULSE_INTERVAL_SECONDS = (.35, 1.5)
PULSE_PROMINENCE_STD_FRACTION = .45
MIN_PULSE_PROMINENCE = 1e-10
MIN_PULSE_PEAKS = 3
MIN_VALID_PULSE_INTERVALS = 2


def eeg_metrics(window, fs, names, iaf_hz=DEFAULT_IAF_HZ):
    # One-second Hann-windowed PSD, updated at 2 Hz.
    labels = [str(label).strip().lower() for label in names]
    f, psd = welch(window, fs=fs, nperseg=len(window), window='hann', axis=0)
    df = float(f[1] - f[0]) if len(f) > 1 else 0.0
    alpha_mask = (f >= iaf_hz - ALPHA_HALF_WIDTH_HZ) & (f <= iaf_hz + ALPHA_HALF_WIDTH_HZ)
    beta_mask = (f >= BETA_BAND_HZ[0]) & (f <= BETA_BAND_HZ[1])
    output = {'IAF': float(iaf_hz), 'AWI': None, 'BAR': None}
    if df <= 0 or not alpha_mask.any() or not beta_mask.any() or not np.isfinite(psd).all():
        output['status'] = 'EEG spectrum insufficient for alpha/beta'
        return output
    alpha = np.sum(psd[alpha_mask], axis=0) * df
    beta = np.sum(psd[beta_mask], axis=0) * df
    valid = np.isfinite(alpha) & np.isfinite(beta) & (alpha > MIN_ALPHA_POWER)
    if np.any(valid):
        # BAR = average beta power / average alpha power, across valid EEG channels.
        output['BAR'] = float(np.mean(beta[valid]) / np.mean(alpha[valid]))
    left = next((labels.index(c) for c in FRONTAL_LEFT_LABELS if c in labels), None)
    right = next((labels.index(c) for c in FRONTAL_RIGHT_LABELS if c in labels), None)
    if left is not None and right is not None and valid[left] and valid[right]:
        output['AWI'] = float(np.log(alpha[right]) - np.log(alpha[left]))
    else:
        output['status'] = 'AWI needs valid F3/F4 or Fp1/Fp2'
    return output


def eda_metrics(window, fs, names, iaf_hz=DEFAULT_IAF_HZ):
    # Tonic SCL is published by the rolling decomposition worker, not this
    # short-window calculator. Never substitute the median of pre-decomposed SC.
    return {'status': 'Waiting for cvxEDA tonic SCL decomposition'}


def ppg_metrics(window, fs, names, iaf_hz=DEFAULT_IAF_HZ):
    # Keep a longer history to calculate HR; a 1-second window alone is insufficient.
    history = window[:, 0]
    peaks, _ = find_peaks(history, distance=max(1, int(fs * PULSE_INTERVAL_SECONDS[0])),
                          prominence=max(np.std(history) * PULSE_PROMINENCE_STD_FRACTION, MIN_PULSE_PROMINENCE))
    if len(peaks) < MIN_PULSE_PEAKS:
        return {'HR': None, 'status': 'Waiting for reliable pulse peaks'}
    intervals = np.diff(peaks) / fs
    valid = intervals[(intervals >= PULSE_INTERVAL_SECONDS[0]) & (intervals <= PULSE_INTERVAL_SECONDS[1])]
    return {'HR': float(60 / np.median(valid)) if len(valid) >= MIN_VALID_PULSE_INTERVALS else None, 'unit': 'bpm'}


@dataclass(frozen=True)
class MetricCalculator:
    window_seconds: float
    calculate: Callable

    def __post_init__(self):
        if not math.isfinite(self.window_seconds) or self.window_seconds <= 0:
            raise ValueError('Metric window must be finite and positive')
        if not callable(self.calculate):
            raise ValueError('Metric calculator must be callable')


METRIC_CALCULATORS = {
    'EEG': MetricCalculator(1., eeg_metrics),
    'EDA': MetricCalculator(1., eda_metrics),
    'PPG': MetricCalculator(10., ppg_metrics),
}
