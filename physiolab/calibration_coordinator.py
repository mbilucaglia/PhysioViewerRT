"""Calibration state and replay transitions, independent of Qt and storage."""
from copy import deepcopy
import numpy as np
from .reference_policy import compatible_references


def recording_snapshot(streams):
    result = {}
    for kind, source in (streams or {}).items():
        stream = {name: deepcopy(value) for name, value in source.items()
                  if name not in ('data', 'timestamps', 'motion_cleaned')}
        for name in ('data', 'timestamps', 'motion_cleaned'):
            if name in source:
                stream[name] = np.array(source[name], copy=True)
                stream[name].setflags(write=False)
        result[kind] = stream
    return result


class CalibrationCoordinator:
    def __init__(self):
        self.loaded_eyc = self.loaded_bsl = self.eyc_recording = None
        self.iaf_hz = 10.
        self.paths = {'EYC': None, 'BSL': None}
        self.base_analysis = {}
        self.streams = {}
        self.cleaned_analysis = None
        self.reference_generation = 0
        self.pending = False
        self.error = None
        self.reference_source = None

    def set_baseline(self, analysis=None, streams=None, filename=None):
        self.reference_generation += 1
        self.base_analysis = deepcopy(analysis or {})
        self.streams = recording_snapshot(streams)
        self.paths['BSL'] = filename
        self.cleaned_analysis = None
        self.loaded_bsl = {'analysis': deepcopy(analysis)} if analysis is not None else None

    def apply(self, kind, meta, filename=None, streams=None):
        if kind == 'EYC':
            # Validate the value before committing any state.
            iaf = float(meta['analysis']['iaf_hz'])
            if not np.isfinite(iaf) or iaf <= 0:
                raise ValueError('Calibration IAF must be finite and positive')
            recorded = recording_snapshot({'EEG': streams['EEG']}) if streams and 'EEG' in streams else {}
            self.loaded_eyc = deepcopy(meta)
            self.eyc_recording = recorded.get('EEG')
            self.iaf_hz = iaf
        else:
            self.set_baseline(meta.get('analysis'), streams, filename)
            self.loaded_bsl = deepcopy(meta)
        self.paths[kind] = filename

    def clear(self, kind):
        if kind == 'EYC':
            self.loaded_eyc = self.eyc_recording = None
            self.iaf_hz = 10.
        else:
            self.set_baseline()
        self.paths[kind] = None

    def request_replay(self, model, live):
        self.reference_generation += 1
        self.pending, self.error = False, None
        self.reference_source = deepcopy(live)
        if self.reference_source is not None:
            self.reference_source.pop('asr_model_id', None)
        eeg = self.streams.get('EEG') if self.loaded_bsl is not None else None
        if self.eyc_recording is None and eeg is None:
            return None
        self.pending = True
        return (self.reference_generation, self.eyc_recording, eeg,
                deepcopy(self.base_analysis), self.iaf_hz, model, deepcopy(live))

    def complete_replay(self, generation, result, error, asr_enabled):
        if generation != self.reference_generation:
            return None
        self.pending, self.error = False, error
        if error:
            return False
        changed = not np.isclose(self.iaf_hz, result['iaf_hz'])
        self.iaf_hz = result['iaf_hz']
        if result['eyc'] is not None and self.loaded_eyc is not None:
            self.loaded_eyc = {**self.loaded_eyc, 'analysis': result['eyc']}
        if result['bsl'] is not None and self.loaded_bsl is not None:
            self.loaded_bsl = {**self.loaded_bsl, 'analysis': result['bsl']}
            if asr_enabled:
                self.cleaned_analysis = result['bsl']
        return changed

    def references(self, live, *, asr_enabled, tonic_configuration):
        return compatible_references((self.loaded_bsl or {}).get('analysis') or {},
            live, self.iaf_hz, asr_enabled=asr_enabled, replay_pending=self.pending,
            replay_error=self.error, tonic_configuration=tonic_configuration)
