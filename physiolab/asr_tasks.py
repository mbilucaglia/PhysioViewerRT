"""Independent ASR training and optional matched EEG BSL reference replay."""
from copy import deepcopy

import numpy as np
from PySide6.QtCore import QThread, Signal

from .calibration import summarize_metric
from .eeg_asr import ASRSettings, StreamingASR, fit_asr
from .metric_observation import source_configuration
from .processing import Processor, METRIC_HOP_SECONDS


def eeg_configuration(eeg):
    return source_configuration('EEG', float(eeg['fs']), list(eeg['channels']),
        eeg.get('preprocessing'), eeg.get('conversion'),
        eeg.get('units') or ['']*len(eeg['channels']))


def fit_training_asr(eeg, settings=None):
    fs, names = float(eeg['fs']), list(eeg['channels'])
    data = np.asarray(eeg['data'], dtype=float)
    config = eeg_configuration(eeg)
    if config['preprocessing']['preset'] == 'off':
        raise ValueError('Use an EEG high-pass filter preset before ASR training')
    stamps = np.asarray(eeg.get('timestamps', []), dtype=float)
    if len(stamps) != len(data) or not np.isfinite(stamps).all() or np.any(np.diff(stamps) <= 0):
        raise ValueError('ASR training needs finite, increasing source timestamps')
    if 'accepted_window_samples' in eeg:
        # Live selection preserves continuous filtering before rejecting windows.
        sizes = eeg['accepted_window_samples']
        if (not sizes or any(not isinstance(n, int) or n < 1 for n in sizes)
                or sum(sizes) != len(data)):
            raise ValueError('Invalid accepted ASR window boundaries')
        offset = 0
        for size in sizes:
            if size/fs < .99 or np.any(np.diff(stamps[offset:offset+size]) > max(.25, 3./fs)):
                raise ValueError('Accepted ASR windows must contain continuous EEG')
            offset += size
        filtered = np.asarray(eeg.get('preprocessed_data'), dtype=float)
        if filtered.shape != data.shape or not np.isfinite(filtered).all():
            raise ValueError('Invalid pre-ASR training samples')
        return fit_asr(filtered, fs, names, config, settings or ASRSettings())
    if len(stamps) > 1 and np.max(np.diff(stamps)) > max(.25, 3./fs):
        raise ValueError('EEG dropped out during ASR training; train again on continuous data')
    processor = Processor('EEG', fs, len(names), names, preprocessing=eeg.get('preprocessing'))
    hop = max(1, round(fs*METRIC_HOP_SECONDS))
    chunks = []
    for start in range(0, len(data), hop):
        processor.push(data[start:start+hop])
        chunks.append(processor.last_filtered_chunk.copy())
    return fit_asr(np.concatenate(chunks), fs, names, config, settings or ASRSettings())


def eeg_reference_analysis(eeg, analysis, iaf_hz, model=None):
    fs, names = float(eeg['fs']), list(eeg['channels'])
    data = np.asarray(eeg['data'], dtype=float)
    config = eeg_configuration(eeg)
    if model is not None and model.source_configuration != config:
        raise ValueError('EEG BSL configuration differs from ASR training; record a matching BSL')
    cleaner = StreamingASR(model) if model is not None else None
    processor = Processor('EEG', fs, len(names), names, iaf_hz=iaf_hz,
                          preprocessing=eeg.get('preprocessing'),
                          sample_transform=cleaner.process if cleaner else None)
    series = {}
    hop = max(1, round(fs*METRIC_HOP_SECONDS))
    for start in range(0, len(data), hop):
        metric = processor.push(data[start:start+hop])
        for key, value in (metric or {}).items():
            if key != 'IAF' and isinstance(value, (int, float)) and np.isfinite(value):
                series.setdefault(key, []).append(value)
    matched = deepcopy(analysis)
    matched.setdefault('metrics', {})['EEG'] = {
        key: summary for key, values in series.items()
        if (summary := summarize_metric(values)) is not None}
    if model is not None:
        config = {**config, 'asr_model_id': model.model_id}
        matched['eeg_asr'] = model.metadata()
    else:
        matched.pop('eeg_asr', None)
    matched.setdefault('source_configurations', {})['EEG'] = config
    matched['iaf_hz_used'] = float(iaf_hz)
    return matched


class ASRFitTask(QThread):
    completed = Signal(object, object, object)  # generation, result, error

    def __init__(self, generation, eeg, settings, parent=None):
        super().__init__(parent)
        self.arguments = eeg, ASRSettings(**settings)
        self.generation = generation

    def run(self):
        try:
            self.completed.emit(self.generation, fit_training_asr(*self.arguments), None)
        except Exception as exc:
            self.completed.emit(self.generation, None, str(exc))


def matched_recording(eeg, live):
    """Recorded samples are already converted; only filtering can be replayed."""
    if live is None:
        return eeg
    recorded = eeg_configuration(eeg)
    for key in ('fs', 'channels', 'conversion', 'units'):
        if recorded[key] != live[key]:
            raise ValueError(f'EEG calibration {key} differs from live source; record matching EYC/BSL')
    return {**eeg, 'preprocessing': dict(live['preprocessing'])}


def calibration_references(eyc, bsl, analysis, iaf_hz, model, live):
    """Replay EYC first, then BSL with its new IAF and the same processing."""
    from .calibration import analyze_eyc
    eye = None
    if eyc is not None:
        eye = analyze_eyc(matched_recording(eyc, live), model)
        iaf_hz = float(eye['iaf_hz'])
    baseline = (eeg_reference_analysis(matched_recording(bsl, live), analysis, iaf_hz, model)
                if bsl is not None else None)
    return {'eyc': eye, 'bsl': baseline, 'iaf_hz': iaf_hz}


class CalibrationReferenceTask(QThread):
    completed = Signal(object, object, object)

    def __init__(self, generation, eyc, bsl, analysis, iaf_hz, model, live, parent=None):
        super().__init__(parent)
        self.generation = generation
        self.arguments = eyc, bsl, deepcopy(analysis), iaf_hz, model, deepcopy(live)

    def run(self):
        try:
            result = calibration_references(*self.arguments)
            self.completed.emit(self.generation, result, None)
        except Exception as exc:
            self.completed.emit(self.generation, None, str(exc))
