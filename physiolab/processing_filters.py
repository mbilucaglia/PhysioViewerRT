"""Pure construction of existing causal preprocessing filters."""
import numpy as np
from scipy.signal import butter, iirnotch, tf2sos

FILTER_PRESETS = {
    'EEG': {'default': (1., 40.), 'wide': (.5, 45.), 'focused': (2., 30.), 'off': None},
    'PPG': {'default': (.5, 8.), 'pulse': (.5, 5.), 'wide': (.5, 10.), 'off': None},
    'EDA': {'default': None, 'smooth_1hz': (None, 1.), 'smooth_2hz': (None, 2.)},
}

def validate_preprocessing(kind, preset='default', notch=True):
    if kind not in FILTER_PRESETS or preset not in FILTER_PRESETS[kind]:
        raise ValueError('Unsupported preprocessing preset')
    return {'preset': preset, 'notch': bool(notch)}

NOTCH_FREQUENCIES_HZ = (50.0, 100.0)
NOTCH_QUALITY_FACTOR = 30.0
FILTER_ORDER = 3
NYQUIST_MARGIN_FRACTION = .45


def build_filter(kind, fs, config):
    """Return SOS coefficients and active notch frequencies; no signal state."""
    sections = []
    notch_frequencies = []
    for frequency in (NOTCH_FREQUENCIES_HZ if config['notch'] else ()):
        if frequency < fs / 2:
            b, a = iirnotch(frequency, Q=NOTCH_QUALITY_FACTOR, fs=fs)
            sections.append(tf2sos(b, a))
            notch_frequencies.append(frequency)
    sos = None
    band = FILTER_PRESETS[kind][config['preset']]
    if band is not None:
        low, high = band
        high = min(high, fs * NYQUIST_MARGIN_FRACTION)
        if low is None:
            sections.append(butter(FILTER_ORDER, high, btype='lowpass', fs=fs, output='sos'))
        elif low < high:
            sections.append(butter(FILTER_ORDER, [low, high], btype='bandpass', fs=fs, output='sos'))
    if sections:
        sos = np.vstack(sections)
    return sos, notch_frequencies
