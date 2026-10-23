"""Bind the minimal Designer-owned EEG ASR controls to session actions."""
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QLabel, QPushButton


class ASRControls(QObject):
    train_requested = Signal()
    fit_requested = Signal(dict)
    enabled_changed = Signal(bool)

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.enable = panel.findChild(QCheckBox, 'EEGASREnable')
        self.cutoff = panel.findChild(QDoubleSpinBox, 'EEGASRCutoff')
        self.status = panel.findChild(QLabel, 'EEGASRStatus')
        self.train = panel.findChild(QPushButton, 'EEGASRTrain')
        self.train.clicked.connect(self.train_requested)
        self._compatible = self._fitted = self._busy = self._has_training = False
        self._source_status = 'Start EEG, then Train ASR. All channels are kept.'
        self._threshold_timer = QTimer(self)
        self._threshold_timer.setSingleShot(True)
        self._threshold_timer.setInterval(400)
        self._threshold_timer.timeout.connect(self._request_fit)
        self.cutoff.valueChanged.connect(self._threshold_changed)
        self.enable.toggled.connect(self.enabled_changed)
        self._sync()

    def settings(self):
        return {'cutoff': self.cutoff.value()}

    def set_source(self, compatible=False, status='', has_training=False):
        self._compatible, self._has_training = bool(compatible), bool(has_training)
        self._source_status = status or 'Train on clean EEG; all channels are kept and corrected.'
        self.panel.setToolTip('Independent ASR training. No channel removal; BSL/EYC are separate.')
        if not has_training:
            self._threshold_timer.stop()
        self._sync()

    def set_fit_state(self, fitted=False, busy=False, status=''):
        self._fitted, self._busy = bool(fitted), bool(busy)
        self.status.setText(status or (
            'Training ASR…' if busy else
            'ASR trained · every channel is kept and corrected.' if fitted else
            self._source_status))
        self._sync()

    def set_enabled(self, enabled):
        self.enable.blockSignals(True)
        self.enable.setChecked(bool(enabled and self._compatible and self._fitted and not self._busy))
        self.enable.blockSignals(False)
        if self.enable.isChecked():
            self.status.setText('ASR active · EEG metrics use the cleaned signal and matching BSL.')

    def _sync(self):
        self.enable.setEnabled(self._compatible and self._fitted and not self._busy)
        self.cutoff.setEnabled(not self._busy)
        self.train.setEnabled(self._compatible and not self._busy)

    def _threshold_changed(self):
        if self._has_training:
            self.status.setText('Updating threshold…')
            self.enable.setEnabled(False)
            self._threshold_timer.start()

    def _request_fit(self):
        if self._has_training and not self._busy:
            self.fit_requested.emit(self.settings())
