"""Independent EEG training, ASR model and baseline reference ownership, without presentation or Qt."""
from .calibration_coordinator import CalibrationCoordinator
from .eeg_asr import ASRError
from .metric_observation import source_configuration


class ASRSession:
    def __init__(self, calibrations=None):
        self.calibrations = calibrations if calibrations is not None else CalibrationCoordinator()
        self.generation = 0
        self.training = None
        self.model = self.cleaned_analysis = None
        self.enabled = self.busy = False

    def set_baseline(self, analysis=None, streams=None, filename=None):
        self.calibrations.set_baseline(analysis, streams, filename)

    @property
    def reference_generation(self):
        return self.calibrations.reference_generation

    @reference_generation.setter
    def reference_generation(self, value):
        self.calibrations.reference_generation = value

    @property
    def base_analysis(self):
        return self.calibrations.base_analysis

    @property
    def streams(self):
        return self.calibrations.streams

    @property
    def filename(self):
        return self.calibrations.paths['BSL']

    @filename.setter
    def filename(self, value):
        self.calibrations.paths['BSL'] = value

    @property
    def cleaned_analysis(self):
        return self.calibrations.cleaned_analysis

    @cleaned_analysis.setter
    def cleaned_analysis(self, value):
        self.calibrations.cleaned_analysis = value

    def set_training(self, eeg):
        self.generation += 1
        self.training = eeg
        self.model = self.cleaned_analysis = None
        self.enabled = False

    @staticmethod
    def source_availability(live):
        if not live:
            return False, 'Start an EEG stream to train ASR.'
        fs, names = live['fs'], live['channels']
        if fs <= 82 or len(names) < 2 or len(set(names)) != len(names):
            return False, 'ASR needs at least two distinct EEG channels sampled above 82 Hz.'
        if live['preprocessing']['preset'] == 'off':
            return False, 'Select an EEG high-pass filter before training ASR.'
        return True, ''

    def availability(self, live=None):
        eeg = self.training
        if not eeg:
            return False, 'Press Train to record a separate clean EEG sample for ASR.', {}
        fs, names = float(eeg['fs']), list(eeg['channels'])
        info = {'name': 'ASR training recording',
                'duration': len(eeg['data'])/fs, 'channels': names, 'sample_rate': fs}
        if fs <= 82 or len(names) < 2 or len(set(names)) != len(names):
            return False, 'ASR requires at least two distinct EEG channels sampled above 82 Hz.', info
        if info['duration'] < 30:
            return False, 'ASR requires at least 30 seconds of EEG training samples.', info
        config = source_configuration('EEG', fs, names, eeg.get('preprocessing'),
                                      eeg.get('conversion'), eeg.get('units') or ['']*len(names),
                                      eeg.get('motion_reference'))
        if config['preprocessing']['preset'] == 'off':
            return False, 'ASR requires high-pass-filtered EEG training data.', info
        if live is not None:
            live = {key: value for key, value in live.items() if key != 'asr_model_id'}
            if live != config:
                return False, 'EEG source settings differ from ASR training. Restore them or train again.', info
        return True, '', info

    def install_fit(self, model):
        self.model, self.cleaned_analysis = model, None
        self.enabled = False

    def set_enabled(self, enabled):
        if enabled and self.model is None:
            raise ASRError('Train ASR on a clean EEG recording before enabling it')
        self.enabled = bool(enabled)

    @property
    def analysis(self):
        return self.cleaned_analysis if self.enabled and self.cleaned_analysis is not None else self.base_analysis
