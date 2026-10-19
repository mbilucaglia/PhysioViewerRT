import numpy as np
from scipy.signal import butter, sosfilt, welch, find_peaks


DEFAULT_IAF_HZ = 10.0
ALPHA_HALF_WIDTH_HZ = 2.0


class Processor:
    def __init__(self, kind, fs, channels, names):
        self.kind, self.fs, self.channels, self.names = kind, float(fs), channels, names
        self.sos = None
        if kind in ('EEG', 'PPG'):
            low, high = (1., 40.) if kind == 'EEG' else (0.5, 8.)
            high = min(high, self.fs * 0.45)
            if low < high:
                self.sos = butter(3, [low, high], btype='bandpass', fs=self.fs, output='sos')
        self.zi = np.zeros((self.sos.shape[0], 2, channels)) if self.sos is not None else None
        self.raw = np.empty((0, channels))
        self.filtered = np.empty((0, channels))
        self.max_samples = max(int(self.fs * 20), int(self.fs) + 2)
        self.since_metric = 0
        self.last_metric = {}

    def push(self, chunk):
        x = np.asarray(chunk, dtype=float).reshape(-1, self.channels)
        if not len(x):
            return None
        if self.sos is not None:
            y, self.zi = sosfilt(self.sos, x, axis=0, zi=self.zi)
        else:
            y = x.copy()
        self.raw = np.concatenate((self.raw, x))[-self.max_samples:]
        self.filtered = np.concatenate((self.filtered, y))[-self.max_samples:]
        self.since_metric += len(x)
        hop = max(1, round(self.fs * .5))
        if self.since_metric >= hop and len(self.filtered) >= round(self.fs):
            self.since_metric %= hop
            self.last_metric = self.metrics()
            return self.last_metric
        return None

    def metrics(self):
        w = self.filtered[-round(self.fs):]
        if self.kind == 'EEG':
            names = [s.lower().strip() for s in self.names]
            left = next((names.index(n) for n in ('f3', 'fp1') if n in names), None)
            right = next((names.index(n) for n in ('f4', 'fp2') if n in names), None)
            if left is None or right is None:
                return {'FAA': None, 'status': 'Need F3/F4 or Fp1/Fp2 channel labels'}
            f, p = welch(w[:, [left, right]], fs=self.fs, nperseg=len(w), axis=0)
            mask = (f >= DEFAULT_IAF_HZ - ALPHA_HALF_WIDTH_HZ) & (f <= DEFAULT_IAF_HZ + ALPHA_HALF_WIDTH_HZ)
            if not mask.any():
                return {'FAA': None, 'status': 'Sampling rate too low'}
            powers = np.maximum(np.sum(p[mask], axis=0) * (f[1] - f[0]), 1e-20)
            return {'FAA': float(np.log(powers[1]) - np.log(powers[0])),
                    'IAF': DEFAULT_IAF_HZ,
                    'alpha_left': float(powers[0]), 'alpha_right': float(powers[1])}
        if self.kind == 'EDA':
            return {'SCL': float(np.median(w[:, 0])), 'unit': 'source units'}
        if self.kind == 'PPG':
            # Keep a longer history to calculate HR; a 1-second window alone is insufficient.
            history = self.filtered[-round(self.fs * 10):, 0]
            peaks, _ = find_peaks(history, distance=max(1, int(self.fs * .35)),
                                  prominence=max(np.std(history) * .45, 1e-10))
            if len(peaks) < 3:
                return {'HR': None, 'status': 'Waiting for reliable pulse peaks'}
            intervals = np.diff(peaks) / self.fs
            valid = intervals[(intervals >= .35) & (intervals <= 1.5)]
            return {'HR': float(60 / np.median(valid)) if len(valid) >= 2 else None, 'unit': 'bpm'}
        return {}
