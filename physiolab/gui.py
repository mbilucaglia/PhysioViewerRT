"""Local two-tab biosignal monitor: waveforms and metrics."""
import json
import time
from collections import deque
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QGridLayout, QTabWidget, QCheckBox,
    QMessageBox, QFileDialog, QDialog, QPlainTextEdit, QToolButton, QMenu
)
from .worker import Receiver, discover
from .channel_selection import channel_labels, validated_indices
from .emotion import RollingEmotionalIndex
from .calibration import (
    analyze_eyc, analyze_bsl, save_calibration, load_calibration, normalize,
    DURATION_SECONDS,
)


class CheckChannelDropdown(QToolButton):
    """Checkbox popup: EEG multiple, EDA/PPG exactly one."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.names = []
        self.actions = []
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setMinimumWidth(125)
        self.menu = QMenu(self)
        self.setMenu(self.menu)
        self.set_channels([])

    def set_channels(self, names):
        self.names = list(names)
        self.actions = []
        self.menu.clear()
        for index, name in enumerate(self.names):
            action = self.menu.addAction(f'{index + 1}: {name}')
            action.setCheckable(True)
            action.setChecked(self.kind == 'EEG' or index == 0)
            action.triggered.connect(lambda checked, i=index: self.select(i, checked))
            self.actions.append(action)
        self.update_label()

    def select(self, index, checked):
        if self.kind in ('EDA', 'PPG'):
            for i, action in enumerate(self.actions):
                action.setChecked(i == index)
        else:
            self.actions[index].setChecked(checked)
        self.update_label()

    def selected_indices(self):
        return [i for i, action in enumerate(self.actions) if action.isChecked()]

    def update_label(self):
        chosen = self.selected_indices()
        if not chosen:
            self.setText('Select channels')
        elif len(chosen) == 1:
            self.setText(f'{self.names[chosen[0]]}')
        else:
            self.setText(f'{len(chosen)} channels')


class CalibrationScreen(QDialog):
    """Fullscreen 60-second calibration prompt. Esc cancels recording."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.started_at = None
        self.setWindowTitle(f'{kind} calibration')
        self.setStyleSheet('background: black; color: white;')
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.instruction = QLabel('Close your eyes' if kind == 'EYC' else '•')
        self.instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.instruction.setStyleSheet(
            'font-size: 52px; color: white;' if kind == 'EYC'
            else 'font-size: 80px; color: white;'
        )
        layout.addWidget(self.instruction)
        self.clock = QLabel('')
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock.setStyleSheet('font-size: 22px; color: #aaa;')
        if kind == 'EYC':
            layout.addWidget(self.clock)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)

    def showEvent(self, event):
        super().showEvent(event)
        self.started_at = time.monotonic()
        self.timer.start()

    def tick(self):
        remaining = max(0, DURATION_SECONDS - (time.monotonic() - self.started_at))
        if self.kind == 'EYC':
            self.clock.setText(f'{remaining:.0f} s')
        if remaining <= 0:
            self.timer.stop()
            self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.timer.stop()
            self.reject()
        else:
            super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PhysioViewerRT — local LSL monitor')
        self.resize(1250, 900)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        controls = QHBoxLayout()
        layout.addLayout(controls)
        self.selectors, self.channel_selectors, self.workers = {}, {}, {}
        self.plots, self.curves = {}, {}
        self.metric_labels, self.metric_status = {}, {}
        self.pending = {}
        self.capture = None
        self.loaded_eyc = None
        self.loaded_bsl = None
        self.latest_metrics = {}
        self.ei_estimator = RollingEmotionalIndex(seconds=60)
        self.metric_keys = [('EEG', 'AWI'), ('EEG', 'BAR'), ('EDA', 'SCL'),
                            ('PPG', 'HR'), ('EI', 'EI')]
        self.metric_history = {key: deque(maxlen=900) for key in self.metric_keys}
        self.iaf_hz = 10.0
        self._configure_calibration_menu()

        for kind in ('EEG', 'EDA', 'PPG'):
            controls.addWidget(QLabel(kind))
            combo = QComboBox()
            combo.setMinimumWidth(160)
            self.selectors[kind] = combo
            controls.addWidget(combo)
            picker = CheckChannelDropdown(kind)
            self.channel_selectors[kind] = picker
            controls.addWidget(picker)
            combo.currentIndexChanged.connect(lambda _, k=kind: self.stream_selection_changed(k))
            button = QPushButton('Connect')
            button.clicked.connect(lambda _, k=kind: self.connect_stream(k))
            controls.addWidget(button)
        refresh = QPushButton('Refresh LSL')
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        signals_page = QWidget()
        signals_layout = QVBoxLayout(signals_page)
        visibility = QHBoxLayout()
        signals_layout.addLayout(visibility)
        self.show_raw = QCheckBox('Raw')
        self.show_raw.setChecked(True)
        self.show_processed = QCheckBox('Filtered / processed')
        self.show_processed.setChecked(True)
        visibility.addWidget(self.show_raw)
        visibility.addWidget(self.show_processed)
        visibility.addStretch()
        signals_layout.addWidget(QLabel(
            'Solid = raw; dashed = processed. Both use the same per-channel display scaling.'
        ))
        for kind in ('EEG', 'EDA', 'PPG'):
            plot = pg.PlotWidget(title=f'{kind} — last 5 seconds')
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setLabel('bottom', 'Time', 's')
            signals_layout.addWidget(plot)
            self.plots[kind] = plot
            self.curves[kind] = []
        self.tabs.addTab(signals_page, 'Raw Data')

        metrics_page = QWidget()
        metrics_layout = QVBoxLayout(metrics_page)
        normalize_row = QHBoxLayout()
        normalize_row.addWidget(QLabel('Normalization'))
        self.normalization = QComboBox()
        for name, value in [('Original (identity)', 'identity'),
                            ('z-score (BSL)', 'zscore'),
                            ('robust z-MAD (BSL)', 'zmad'),
                            ('robust IQR (BSL)', 'robust_iqr'),
                            ('fixed min-max (BSL)', 'minmax')]:
            self.normalization.addItem(name, value)
        self.normalization.currentIndexChanged.connect(self.refresh_metrics)
        normalize_row.addWidget(self.normalization)
        normalize_row.addStretch()
        metrics_layout.addLayout(normalize_row)
        self.calibration_state = QLabel('EYC: none (default IAF 10 Hz) | BSL: none')
        metrics_layout.addWidget(self.calibration_state)
        self.metric_plot = pg.PlotWidget(title='Combined live metrics — last 5 minutes')
        self.metric_plot.setLabel('bottom', 'Time relative to now', units='s')
        self.metric_plot.showGrid(x=True, y=True, alpha=.2)
        self.metric_plot.addLegend()
        self.metric_curves = {}
        for key, color in zip(self.metric_keys, (
            '#e69f00', '#56b4e9', '#009e73', '#cc79a7', '#d55e00'
        )):
            self.metric_curves[key] = self.metric_plot.plot(
                name=f'{key[0]} / {key[1]}', pen=pg.mkPen(color, width=2),
                connect='finite',
            )
        metrics_layout.addWidget(self.metric_plot, stretch=4)
        metrics_layout.addWidget(QLabel(
            'Original mode uses mixed units on one axis. Normalized modes '
            'use stored BSL references; missing data appear as gaps.'
        ))
        metrics_grid = QGridLayout()
        metrics_layout.addLayout(metrics_grid)
        for row, (kind, keys) in enumerate((
            ('EEG', ('IAF', 'AWI', 'BAR')),
            ('EDA', ('SCL',)),
            ('PPG', ('HR',)),
            ('EI', ('EI',)),
        )):
            group = QVBoxLayout()
            title = QLabel(f'<h2>{kind} metrics</h2>')
            group.addWidget(title)
            for key in keys:
                label = QLabel(f'{key}: —')
                label.setStyleSheet('font-size: 18px; padding: 7px;')
                group.addWidget(label)
                self.metric_labels[(kind, key)] = label
            status = QLabel('Waiting for stream / valid window')
            status.setWordWrap(True)
            group.addWidget(status)
            self.metric_status[kind] = status
            group.addStretch()
            metrics_grid.addLayout(group, row, 0)
        metrics_grid.setRowStretch(3, 1)
        self.tabs.addTab(metrics_page, 'Metrics')

        self.statusBar().showMessage('Start an LSL source, then press Refresh LSL.')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.draw)
        self.timer.start(40)
        self.refresh()

    def refresh(self):
        try:
            streams = discover()
            for kind, combo in self.selectors.items():
                combo.clear()
                for info in streams:
                    match = info.type().upper() in (('EDA', 'GSR') if kind == 'EDA' else (kind,))
                    if match:
                        combo.addItem(
                            f'{info.name()} ({info.channel_count()} ch, '
                            f'{info.nominal_srate():g} Hz)', info
                        )
            self.statusBar().showMessage(f'Found {len(streams)} LSL streams')
        except Exception as exc:
            self.statusBar().showMessage(str(exc))

    def connect_stream(self, kind):
        info = self.selectors[kind].currentData()
        if info is None:
            self.statusBar().showMessage(f'No {kind} stream selected')
            return
        if kind in self.workers:
            self.workers[kind].stop()
        self.pending.pop(kind, None)
        for key in self.metric_keys:
            if key[0] == kind:
                self.metric_history[key].clear()
        if kind in ('PPG', 'EDA'):
            self.ei_estimator = RollingEmotionalIndex(seconds=60)
            self.metric_history[('EI', 'EI')].clear()
            self.latest_metrics.pop('EI', None)
        self.latest_metrics.pop(kind, None)
        worker = Receiver(info, kind)
        worker.updated.connect(self.receive)
        worker.samples_received.connect(self.capture_samples)
        worker.stream_ready.connect(self.ready_stream)
        worker.iaf_hz = self.iaf_hz
        worker.failure.connect(self.statusBar().showMessage)
        self.workers[kind] = worker
        worker.start()

    def receive(self, kind, raw, processed, names, metric, fs):
        self.pending[kind] = (raw, processed, names, fs)
        if metric is None:
            return
        now = time.monotonic()
        self.latest_metrics[kind] = metric
        for modality, name in self.metric_keys:
            if modality == kind:
                val = metric.get(name)
                self.metric_history[(modality, name)].append(
                    (now, float(val) if isinstance(val, (int, float))
                     and np.isfinite(val) else float('nan'))
                )
        if kind in ('PPG', 'EDA'):
            name = 'HR' if kind == 'PPG' else 'SCL'
            self.ei_estimator.update(kind, metric.get(name), now)
            value = self.ei_estimator.value(now)
            self.latest_metrics['EI'] = {
                'EI': value,
                'status': 'Rolling 60 s within-signal HR/GSR standardization'
                if value is not None else 'Waiting for 60 s valid HR/GSR data',
            }
            self.metric_history[('EI', 'EI')].append(
                (now, float(value) if value is not None else float('nan'))
            )
        self.refresh_metrics()

    def displayed_value(self, kind, name, value):
        if value is None or not isinstance(value, (int, float)) or not np.isfinite(value):
            return None
        mode = self.normalization.currentData()
        if mode == 'identity' or (kind == 'EEG' and name == 'IAF'):
            return float(value)
        refs = ((self.loaded_bsl or {}).get('analysis') or {}).get('metrics', {})
        reference = refs.get(kind, {}).get(name)
        if reference is None:
            return None
        # Live EI derives from within-signal z scores; any display transform
        # uses the *EI* reference statistics measured during BSL.
        return normalize(value, reference, mode)

    def refresh_metrics(self, *_):
        for (kind, name), label in self.metric_labels.items():
            raw = self.latest_metrics.get(kind, {}).get(name)
            value = self.displayed_value(kind, name, raw)
            label.setText(f'{name}: {value:.3f}' if value is not None else f'{name}: —')
        for kind, label in self.metric_status.items():
            label.setText(self.latest_metrics.get(kind, {}).get('status', 'Waiting for data'))
        self.refresh_metric_plot()

    def refresh_metric_plot(self):
        now = time.monotonic()
        for (kind, name), curve in self.metric_curves.items():
            points = [(t, val) for t, val in self.metric_history[(kind, name)]
                      if now - t <= 300]
            if not points:
                curve.clear()
                continue
            timestamps = np.asarray([t - now for t, _ in points], dtype=float)
            display = [self.displayed_value(kind, name, val) for _, val in points]
            values = np.asarray(
                [float(v) if v is not None else np.nan for v in display],
                dtype=float,
            )
            curve.setData(timestamps, values, connect='finite')
        self.metric_plot.setXRange(-300, 0, padding=0)

    def draw(self):
        # Acquisition and metric computation continue regardless of the selected tab.
        if self.tabs.currentIndex() != 0:
            return
        for kind, (raw, processed, names, fs) in list(self.pending.items()):
            n = min(raw.shape[1], 8 if kind == 'EEG' else 2)
            plot = self.plots[kind]
            if len(self.curves[kind]) != 2 * n:
                plot.clear()
                curves = []
                for i in range(n):
                    color = pg.intColor(i, hues=max(n, 3))
                    curves.append(plot.plot(
                        name=f'{names[i]} raw', pen=pg.mkPen(color, width=1)
                    ))
                    curves.append(plot.plot(
                        name=f'{names[i]} processed',
                        pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine)
                    ))
                self.curves[kind] = curves
            count = min(len(raw), len(processed))
            if count < 1:
                continue
            t = (np.arange(count) - count + 1) / fs
            for i in range(n):
                r = raw[-count:, i]
                p = processed[-count:, i]
                scale = float(np.std(r))
                if not np.isfinite(scale) or scale < 1e-12:
                    scale = 1.
                raw_y = (r - np.median(r)) / scale + i * 6
                processed_y = (p - np.median(r)) / scale + i * 6
                self.curves[kind][2*i].setData(t, raw_y) if self.show_raw.isChecked() else self.curves[kind][2*i].clear()
                self.curves[kind][2*i+1].setData(t, processed_y) if self.show_processed.isChecked() else self.curves[kind][2*i+1].clear()
            self.pending.pop(kind, None)


    def _configure_calibration_menu(self):
        menu = self.menuBar().addMenu('Calibration')
        menu.addAction('Record EYC (60 s)...', lambda: self.record_calibration('EYC'))
        menu.addAction('Record BSL (60 s)...', lambda: self.record_calibration('BSL'))
        menu.addSeparator()
        menu.addAction('Load EYC file...', lambda: self.load_existing('EYC'))
        menu.addAction('Load BSL file...', lambda: self.load_existing('BSL'))

    def ready_stream(self, kind, channels, fs):
        self.statusBar().showMessage(f'{kind} ready: {len(channels)} channels at {fs:g} Hz')

    def capture_samples(self, kind, samples, timestamps, channels, fs):
        session = self.capture
        if session is None or kind not in session['streams']:
            return
        if time.monotonic() > session['deadline']:
            return
        arr = np.asarray(samples, dtype=float)
        ts = np.asarray(timestamps, dtype=float)
        if arr.ndim != 2 or len(arr) != len(ts) or not len(ts):
            return
        item = session['streams'][kind]
        if item['channels'] != list(channels) or item['fs'] != float(fs):
            session['errors'].append(f'{kind} stream metadata changed')
            return
        item['chunks'].append(arr.copy())
        item['times'].append(ts.copy())

    def record_calibration(self, kind):
        if self.capture is not None:
            QMessageBox.warning(self, 'Calibration', 'A calibration is already running.')
            return
        connected = {modality: worker for modality, worker in self.workers.items()
                     if worker.isRunning() and worker.active}
        if kind == 'EYC' and 'EEG' not in connected:
            QMessageBox.warning(self, 'EYC calibration', 'Connect an EEG LSL stream first.')
            return
        if kind == 'BSL' and not connected:
            QMessageBox.warning(self, 'BSL calibration', 'Connect at least one LSL stream first.')
            return
        instruction = ('Close your eyes for 60 seconds. Press Esc to cancel.'
                       if kind == 'EYC' else
                       'Look steadily at the white dot for 60 seconds. Press Esc to cancel.')
        QMessageBox.information(self, f'{kind} instructions', instruction)
        # Record every connected modality during BSL, EEG during EYC.
        included = ['EEG'] if kind == 'EYC' else list(connected)
        meta = {}
        for modality in included:
            worker = connected[modality]
            info = worker.info
            channels = []
            ch = info.desc().child('channels').child('channel')
            for idx in range(info.channel_count()):
                channels.append(ch.child_value('label') or f'Ch{idx+1}')
                ch = ch.next_sibling()
            meta[modality] = {
                'fs': float(info.nominal_srate()), 'channels': channels,
                'chunks': [], 'times': [],
            }
        screen = CalibrationScreen(kind, self)
        self.capture = {
            'kind': kind, 'streams': meta, 'errors': [],
            'deadline': time.monotonic() + DURATION_SECONDS + 1,
        }
        result = screen.exec()
        session = self.capture
        self.capture = None
        if kind == 'EYC':
            QMessageBox.information(self, 'EYC finished', 'Open your eyes.')
        if result != QDialog.DialogCode.Accepted:
            self.statusBar().showMessage(f'{kind} cancelled; no calibration saved')
            return
        if session['errors']:
            QMessageBox.warning(self, 'Calibration invalid', '\n'.join(session['errors']))
            return
        streams = {}
        for modality, value in session['streams'].items():
            if not value['chunks']:
                continue
            data = np.concatenate(value['chunks'])
            stamps = np.concatenate(value['times'])
            duration = len(data) / value['fs']
            if duration < 55:
                QMessageBox.warning(self, 'Recording incomplete',
                                    f'{modality}: only {duration:.1f} s of samples. Please retry.')
                return
            streams[modality] = {
                'data': data, 'timestamps': stamps,
                'fs': value['fs'], 'channels': value['channels'],
            }
        try:
            analysis = self.analyze_calibration(kind, streams)
        except Exception as exc:
            QMessageBox.warning(self, 'Calibration analysis failed', str(exc))
            return
        self.inspect_calibration(kind, analysis)
        answer = QMessageBox.question(
            self, f'Save {kind} calibration?', 'Save recorded calibration data and analysis?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, f'Save {kind}', f'{kind.lower()}_calibration.npz', 'Calibration (*.npz)'
        )
        if not filename:
            return
        if not filename.lower().endswith('.npz'):
            filename += '.npz'
        try:
            save_calibration(filename, kind, streams, analysis)
            self.apply_calibration(kind, {'analysis': analysis})
            self.statusBar().showMessage(f'Saved {kind}: {filename}')
        except Exception as exc:
            QMessageBox.critical(self, 'Save failed', str(exc))

    def analyze_calibration(self, kind, streams):
        if kind == 'EYC':
            if 'EEG' not in streams:
                raise ValueError('An EEG stream is required')
            return analyze_eyc(streams['EEG'])
        return analyze_bsl(streams, iaf_hz=self.iaf_hz)

    def inspect_calibration(self, kind, analysis):
        dlg = QDialog(self)
        dlg.setWindowTitle(f'{kind} calibration inspection')
        dlg.resize(760, 570)
        layout = QVBoxLayout(dlg)
        if kind == 'EYC':
            layout.addWidget(QLabel(
                f"Posterior alpha center of gravity: {analysis['iaf_hz']:.2f} Hz "
                f"(7–13 Hz), channels: {', '.join(analysis['posterior_channels'])}"
            ))
            plot = pg.PlotWidget(title='Average posterior-channel PSD (Welch, Hann, 1 s, 50% overlap)')
            plot.plot(analysis['psd_hz'], analysis['mean_psd'], pen=pg.mkPen('#33aaff', width=2))
            plot.addLine(x=analysis['iaf_hz'], pen=pg.mkPen('red', width=2))
            plot.setXRange(3, 20)
            plot.setLabel('bottom', 'Frequency', 'Hz')
            layout.addWidget(plot)
        else:
            view = QPlainTextEdit()
            view.setReadOnly(True)
            lines = [f"IAF used: {analysis['iaf_hz_used']:.2f} Hz", ""]
            for modality, fields in analysis['metrics'].items():
                lines.append(f"{modality}")
                for name, stats in fields.items():
                    lines.append(
                        f"  {name}: μ={stats['mu']:.5g} σ={stats['sigma']:.5g} "
                        f"median={stats['median']:.5g} IQR={stats['iqr']:.5g} "
                        f"(N={stats['valid_windows']})"
                    )
                lines.append('')
            view.setPlainText('\n'.join(lines))
            layout.addWidget(view)
        close = QPushButton('Close inspection')
        close.clicked.connect(dlg.accept)
        layout.addWidget(close)
        dlg.exec()

    def apply_calibration(self, kind, meta):
        if kind == 'EYC':
            self.loaded_eyc = meta
            self.iaf_hz = float(meta['analysis']['iaf_hz'])
            for worker in self.workers.values():
                if worker.kind == 'EEG':
                    worker.iaf_hz = self.iaf_hz
        else:
            self.loaded_bsl = meta
        self.calibration_state.setText(
            f"EYC: {self.iaf_hz:.2f} Hz"
            f" | BSL: {'loaded' if self.loaded_bsl else 'none'}"
        )
        self.refresh_metrics()

    def load_existing(self, kind):
        filename, _ = QFileDialog.getOpenFileName(
            self, f'Open {kind} calibration', '', 'Calibration (*.npz)'
        )
        if not filename:
            return
        try:
            meta, streams = load_calibration(filename, kind)
            # Inspect the saved result, also recompute if an older file lacks it.
            analysis = meta.get('analysis') or self.analyze_calibration(kind, streams)
            self.inspect_calibration(kind, analysis)
            self.apply_calibration(kind, {'analysis': analysis})
            self.statusBar().showMessage(f'Loaded {kind}: {filename}')
        except Exception as exc:
            QMessageBox.critical(self, f'Cannot load {kind}', str(exc))

    def closeEvent(self, event):
        for worker in self.workers.values():
            worker.stop()
        super().closeEvent(event)
