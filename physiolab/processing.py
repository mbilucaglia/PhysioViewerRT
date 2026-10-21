import numpy as np
from scipy.signal import butter, sosfilt, welch, find_peaks, iirnotch, tf2sos
from .signal_buffer import SampleRing

FILTER_PRESETS = {
    'EEG': {'default': (1., 40.), 'wide': (.5, 45.), 'focused': (2., 30.), 'off': None},
    'PPG': {'default': (.5, 8.), 'pulse': (.5, 5.), 'wide': (.5, 10.), 'off': None},
    'EDA': {'default': None, 'smooth_1hz': (None, 1.), 'smooth_2hz': (None, 2.)},
}

def validate_preprocessing(kind, preset='default', notch=True):
    if kind not in FILTER_PRESETS or preset not in FILTER_PRESETS[kind]:
        raise ValueError('Unsupported preprocessing preset')
    return {'preset': preset, 'notch': bool(notch)}



DEFAULT_IAF_HZ = 10.0
ALPHA_HALF_WIDTH_HZ = 2.0


class Processor:
    def __init__(self, kind, fs, channels, names, iaf_hz=DEFAULT_IAF_HZ, preprocessing=None):
        self.kind, self.fs, self.channels, self.names = kind, float(fs), channels, names
        self.iaf_hz = float(iaf_hz)
        config = validate_preprocessing(kind, **(preprocessing or {}))
        self.preprocessing = config
        sections = []
        self.notch_frequencies = []
        for frequency in ((50.0, 100.0) if config['notch'] else ()):
            if frequency < self.fs / 2:
                b, a = iirnotch(frequency, Q=30.0, fs=self.fs)
                sections.append(tf2sos(b, a))
                self.notch_frequencies.append(frequency)
        self.sos = None
        band = FILTER_PRESETS[kind][config['preset']]
        if band is not None:
            low, high = band
            high = min(high, self.fs * 0.45)
            if low is None:
                sections.append(butter(3, high, btype='lowpass', fs=self.fs, output='sos'))
            elif low < high:
                sections.append(butter(3, [low, high], btype='bandpass', fs=self.fs, output='sos'))
        if sections:
            self.sos = np.vstack(sections)
        self.zi = np.zeros((self.sos.shape[0], 2, channels)) if self.sos is not None else None
        self.max_samples = max(int(self.fs * 20), int(self.fs) + 2)
        self._raw_history = SampleRing(self.max_samples, channels)
        self._filtered_history = SampleRing(self.max_samples, channels)
        self.last_filtered_chunk = np.empty((0, channels))
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
        self._raw_history.append(x)
        self._filtered_history.append(y)
        self.last_filtered_chunk = y
        self.since_metric += len(x)
        hop = max(1, round(self.fs * .5))
        if self.since_metric >= hop and len(self._filtered_history) >= round(self.fs):
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
        w = self._filtered_history.tail(round(self.fs))
        if self.kind == 'EEG':
            # One-second Hann-windowed PSD, updated at 2 Hz.
            labels = [str(label).strip().lower() for label in self.names]
            f, psd = welch(w, fs=self.fs, nperseg=len(w), window='hann', axis=0)
            df = float(f[1] - f[0]) if len(f) > 1 else 0.0
            alpha_mask = (f >= self.iaf_hz - ALPHA_HALF_WIDTH_HZ) & (f <= self.iaf_hz + ALPHA_HALF_WIDTH_HZ)
            beta_mask = (f >= 13.0) & (f <= 30.0)
            output = {'IAF': float(self.iaf_hz), 'AWI': None, 'BAR': None}
            if df <= 0 or not alpha_mask.any() or not beta_mask.any() or not np.isfinite(psd).all():
                output['status'] = 'EEG spectrum insufficient for alpha/beta'
                return output
            alpha = np.sum(psd[alpha_mask], axis=0) * df
            beta = np.sum(psd[beta_mask], axis=0) * df
            valid = np.isfinite(alpha) & np.isfinite(beta) & (alpha > 1e-18)
            if np.any(valid):
                # BAR = average beta power / average alpha power, across valid EEG channels.
                output['BAR'] = float(np.mean(beta[valid]) / np.mean(alpha[valid]))
            left = next((labels.index(c) for c in ('f3','fp1') if c in labels), None)
            right = next((labels.index(c) for c in ('f4','fp2') if c in labels), None)
            if left is not None and right is not None and valid[left] and valid[right]:
                output['AWI'] = float(np.log(alpha[right]) - np.log(alpha[left]))
            else:
                output['status'] = 'AWI needs valid F3/F4 or Fp1/Fp2'
            return output
        if self.kind == 'EDA':
            return {'SCL': float(np.median(w[:, 0])), 'unit': 'source units'}
        if self.kind == 'PPG':
            # Keep a longer history to calculate HR; a 1-second window alone is insufficient.
            history = self._filtered_history.tail(round(self.fs * 10))[:, 0]
            peaks, _ = find_peaks(history, distance=max(1, int(self.fs * .35)),
                                  prominence=max(np.std(history) * .45, 1e-10))
            if len(peaks) < 3:
                return {'HR': None, 'status': 'Waiting for reliable pulse peaks'}
            intervals = np.diff(peaks) / self.fs
            valid = intervals[(intervals >= .35) & (intervals <= 1.5)]
            return {'HR': float(60 / np.median(valid)) if len(valid) >= 2 else None, 'unit': 'bpm'}
        return {}
