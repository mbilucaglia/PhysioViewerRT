"""Run calibration analysis without stopping acquisition or Qt painting."""
import logging
from copy import deepcopy
from PySide6.QtCore import QThread, Signal

from .calibration import analyze_eyc, analyze_bsl
from .calibration_storage import save_calibration, load_calibration
from .calibration_coordinator import recording_snapshot
from .calibration_contracts import CalibrationSaved, CalibrationLoaded

logger = logging.getLogger(__name__)


class CalibrationIOTask(QThread):
    completed = Signal(object, object)

    def __init__(self, operation, path, kind, streams=None, analysis=None, parent=None):
        super().__init__(parent)
        self.operation, self.path, self.kind = operation, path, kind
        # One owned copy for save; edits to a caller's recording cannot race I/O.
        self.streams = recording_snapshot(streams) if operation == 'save' else None
        self.analysis = deepcopy(analysis)

    def run(self):
        try:
            if self.operation == 'save':
                save_calibration(self.path, self.kind, self.streams, self.analysis)
                result = CalibrationSaved(str(self.path))
            elif self.operation == 'load':
                meta, streams = load_calibration(self.path, self.kind)
                for stream in streams.values():
                    stream['data'].setflags(write=False)
                    stream['timestamps'].setflags(write=False)
                    if 'motion_cleaned' in stream:
                        stream['motion_cleaned'].setflags(write=False)
                result = CalibrationLoaded(meta, streams)
            else:
                raise ValueError(f'Unknown calibration operation: {self.operation}')
            self.completed.emit(result, None)
        except Exception as exc:
            logger.exception('Calibration file operation failed (operation=%s, kind=%s)',
                             self.operation, self.kind)
            self.completed.emit(None, str(exc))


class CalibrationAnalysisTask(QThread):
    completed = Signal(object, object)

    def __init__(self, kind, streams, iaf_hz, parent=None, eeg_asr_model=None):
        super().__init__(parent)
        self.kind, self.streams, self.iaf_hz = kind, streams, iaf_hz
        self.eeg_asr_model = eeg_asr_model

    def run(self):
        try:
            result = (analyze_eyc(self.streams['EEG'], self.eeg_asr_model) if self.kind == 'EYC'
                      else analyze_bsl(self.streams, self.iaf_hz, self.eeg_asr_model))
            self.completed.emit(result, None)
        except Exception as exc:
            logger.exception('Calibration analysis failed (kind=%s)', self.kind)
            self.completed.emit(None, str(exc))
