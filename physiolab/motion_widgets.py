"""Optional per-modality accelerometer source and axis mapping."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox, QLabel, QSpinBox
from .motion_reduction import MotionReference, is_acc_stream, acc_axes


class MotionControls(QWidget):
    changed = Signal()
    metadata_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
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
            spin = QSpinBox()
            spin.setRange(1, 3)
            spin.setFixedWidth(52)
            # NoButtons gives a zero-width editor with Qt's Windows stylesheet.
            spin.setStyleSheet(
                'QSpinBox::up-button, QSpinBox::down-button '
                '{ width: 0px; height: 0px; border: none; } '
                'QSpinBox::up-arrow, QSpinBox::down-arrow '
                '{ image: none; width: 0px; height: 0px; }')
            spin.setValue(len(self.axes)+1)
            spin.setAccessibleName('ACC '+name+' channel (1-based)')
            self.axes.append(spin)
            row.addWidget(spin)
            spin.valueChanged.connect(self.changed)
        row.addStretch()
        self.enabled = QCheckBox('Adaptive ACC (NLMS)')
        self.enabled.setToolTip('Clean the input signal using X/Y/Z before filtering, ASR, IAF and baseline metrics. May also attenuate physiological components correlated with motion. Raw samples are preserved. Record matching EYC/BSL and ASR training with the same ACC settings.')
        row.addWidget(self.enabled)
        layout.addLayout(row)
        self.status = QLabel('ACC off')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.source.currentIndexChanged.connect(self._selected)
        self.enabled.toggled.connect(self.changed)
        self._selected()

    def _selected(self):
        info = self.source.currentData()
        for axis in self.axes:
            axis.blockSignals(True)
            axis.setMaximum(info.channel_count() if info is not None else 3)
            axis.setEnabled(info is not None)
            axis.blockSignals(False)
        self.enabled.setEnabled(info is not None)
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
        if indices is not None and [s.value() for s in self.axes] == [1, 2, 3]:
            for spin, idx in zip(self.axes, indices):
                spin.blockSignals(True)
                spin.setValue(idx+1)
                spin.blockSignals(False)
            self.changed.emit()
        for spin in self.axes:
            spin.setToolTip('\n'.join(f'{i+1}: {name}' for i, name in enumerate(labels)))

    def reference(self):
        info = self.source.currentData()
        if info is None:
            return None
        return MotionReference(info, tuple(spin.value()-1 for spin in self.axes), self.enabled.isChecked())

    def signature(self):
        info = self.source.currentData()
        return None if info is None else (info.uid(), tuple(s.value()-1 for s in self.axes), self.enabled.isChecked())

    def update_status(self, view):
        if view is None:
            self.status.setText('ACC off' if self.source.currentData() is None else 'ACC ready for next stream start')
            return
        state, values = getattr(view, 'motion_feedback', ('ACC off', None))
        suffix = '' if values is None else ' | X/Y/Z: '+', '.join(f'{v:.3g}' for v in values)
        self.status.setText(state+suffix)
