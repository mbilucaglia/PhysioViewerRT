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


class EEGReferenceTask(QThread):
    completed = Signal(object, object, object)

    def __init__(self, generation, eeg, analysis, iaf_hz, model, parent=None):
        super().__init__(parent)
        self.generation = generation
        self.arguments = eeg, analysis, iaf_hz, model

    def run(self):
        try:
            self.completed.emit(self.generation, eeg_reference_analysis(*self.arguments), None)
        except Exception as exc:
            self.completed.emit(self.generation, None, str(exc))
