"""Optional per-modality accelerometer source and axis mapping."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                               QCheckBox, QLabel, QDoubleSpinBox, QPushButton)
from .motion_reduction import MotionReference, is_acc_stream, acc_axes


class MotionControls(QWidget):
    calibration_requested = Signal(object)
    changed = Signal()
    metadata_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.static_calibration = None
        self.calibration_revision = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.source = QComboBox()
        self.source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.source.setMinimumContentsLength(16)
        self.source.setAccessibleName('Accelerometer LSL reference')
        self.source.addItem('ACC: none', None)
        self.source.setToolTip('Optional motion reference. ACC/IMU candidates first; mixed streams can be mapped manually.')
        layout.addWidget(self.source)
        row = QHBoxLayout()
        self.axes = []
        for name in 'XYZ':
            row.addWidget(QLabel(name))
            selector = QComboBox()
            selector.setMinimumContentsLength(10)
            selector.setAccessibleName('ACC '+name+' channel')
            selector.addItem(f'Ch{len(self.axes)+1}', len(self.axes))
            self.axes.append(selector)
            row.addWidget(selector)
            selector.currentIndexChanged.connect(self.clear_calibration)
        row.addStretch()
        self.enabled = QCheckBox('Adaptive ACC (NLMS)')
        self.enabled.setToolTip('Clean the input signal using X/Y/Z before filtering, ASR, IAF and baseline metrics. May also attenuate physiological components correlated with motion. Raw samples are preserved. Record matching EYC/BSL and ASR training with the same ACC settings.')
        row.addWidget(self.enabled)
        row.addWidget(QLabel('Threshold (mg)'))
        self.intervention_threshold = QDoubleSpinBox()
        self.intervention_threshold.setRange(.1, 100.)
        self.intervention_threshold.setDecimals(1)
        self.intervention_threshold.setSingleStep(.5)
        self.intervention_threshold.setValue(5.)
        self.intervention_threshold.setAccessibleName('ACC intervention threshold in milligravity')
        self.intervention_threshold.setToolTip(
            'Minimum movement magnitude relative to gravity before NLMS adapts. '
            'The adaptive relative-noise gate can require stronger movement.')
        row.addWidget(self.intervention_threshold)
        layout.addLayout(row)
        self.calibrate = QPushButton('Calibra zero ACC — Stai fermo (5 s)')
        self.calibrate.clicked.connect(self.request_calibration)
        layout.addWidget(self.calibrate)
        self.calibration_status = QLabel('Zero ACC non calibrato')
        layout.addWidget(self.calibration_status)
        self.status = QLabel('ACC off')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.source.currentIndexChanged.connect(self._selected)
        self.enabled.toggled.connect(self.changed)
        self.intervention_threshold.valueChanged.connect(self.changed)
        self._selected()

    def request_calibration(self) -> None:
        try:
            reference = self.reference()
        except ValueError as exc:
            self.calibration_status.setText(str(exc))
            return
        self.calibration_requested.emit(reference)

    def clear_calibration(self, *_):
        self.calibration_revision += 1
        self.static_calibration = None
        self.calibration_status.setText("Zero ACC non calibrato")
        self.changed.emit()

    def _selected(self):
        self.clear_calibration()
        info = self.source.currentData()
        for axis in self.axes:
            axis.setEnabled(info is not None)
        if info is not None:
            self._set_axis_labels([f'Ch{i+1}' for i in range(info.channel_count())])
        self.enabled.setEnabled(info is not None)
        self.calibrate.setEnabled(info is not None)
        if info is not None:
            self.status.setText('ACC selected; verify X/Y/Z channels')
            self.metadata_requested.emit(info)
        else:
            self.status.setText('ACC off')
        self.changed.emit()

    def set_streams(self, streams):
        old = self.source.currentData()
        uid = old.uid() if old is not None else None
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem('ACC: none', None)
        for info in sorted(streams, key=lambda s: not is_acc_stream(s)):
            if info.channel_count() >= 3 and info.nominal_srate() > 0:
                prefix = 'ACC candidate' if is_acc_stream(info) else 'Manual mapping'
                self.source.addItem(f'{prefix}: {info.name()} [{info.type()}] ({info.nominal_srate():g} Hz)', info)
                if info.uid() == uid:
                    self.source.setCurrentIndex(self.source.count()-1)
        # Discovery is a snapshot, not proof of disconnection. Retain selection
        # and its inlet on a transient missed announcement.
        if old is not None and self.source.currentIndex() == 0:
            self.source.addItem(f'ACC selected (not discovered): {old.name()}', old)
            self.source.setCurrentIndex(self.source.count()-1)
        self.source.blockSignals(False)

    def set_labels(self, uid, labels):
        info = self.source.currentData()
        if info is None or info.uid() != uid:
            return
        indices = acc_axes(labels)
        # Only auto-map untouched default axes; never replace user mapping.
        current = [axis.currentData() for axis in self.axes]
        self._set_axis_labels(labels)
        if indices is not None and current == [0, 1, 2]:
            for axis, idx in zip(self.axes, indices):
                axis.setCurrentIndex(axis.findData(idx))
            self.changed.emit()

    def _set_axis_labels(self, labels):
        for axis in self.axes:
            selected = axis.currentData()
            axis.blockSignals(True)
            axis.clear()
            for index, name in enumerate(labels):
                axis.addItem(f'{name} (Ch{index+1})', index)
            target = axis.findData(selected)
            axis.setCurrentIndex(target if target >= 0 else 0)
            axis.blockSignals(False)
            axis.setToolTip('Select the stream channel used as this ACC axis')

    def reference(self):
        info = self.source.currentData()
        if info is None:
            return None
        return MotionReference(info, tuple(axis.currentData() for axis in self.axes),
                               self.enabled.isChecked(), self.intervention_threshold.value(), self.static_calibration)

    def signature(self):
        info = self.source.currentData()
        return None if info is None else (
            info.uid(), tuple(axis.currentData() for axis in self.axes),
            self.enabled.isChecked(), self.intervention_threshold.value()) + (
                (self.static_calibration,) if self.static_calibration is not None else ())

    def update_status(self, view):
        if view is None:
            self.status.setText('ACC off' if self.source.currentData() is None else 'ACC ready for next stream start')
            return
        state, values = getattr(view, 'motion_feedback', ('ACC off', None))
        suffix = '' if values is None else ' | X/Y/Z: '+', '.join(f'{v:.3g}' for v in values)
        threshold = f' | threshold {self.intervention_threshold.value():g} mg'
        self.status.setText(state+threshold+suffix)
