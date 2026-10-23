"""Run calibration analysis without stopping acquisition or Qt painting."""
from PySide6.QtCore import QThread, Signal

from .calibration import analyze_eyc, analyze_bsl


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
            self.completed.emit(None, str(exc))
