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
    QMessageBox, QFileDialog, QDialog, QPlainTextEdit, QToolButton, QMenu,
    QScrollArea, QSizePolicy
)
from .worker import Receiver, discover
from .channel_selection import channel_labels, full_channel_labels, validated_indices
from .emotion import BaselineEmotionalIndex
from .metric_display import prepare_metric_curve
from .raw_timing import clean_lsl_chunk, visible_chunk, SmoothViewportClock
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
        self.setFixedWidth(210)
        self.setToolTip('Choose channels; source labels are shown in the checklist')
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
            self.setToolTip('No channels selected. Open the dropdown to choose.')
            return
        selected = [f'{i + 1}: {self.names[i]}' for i in chosen]
        # Show the actual labels instead of just "N channels". Width is
        # bounded; the tooltip gives the unabridged list on hover.
        full = ', '.join(selected)
        self.setText(self.fontMetrics().elidedText(
            full, Qt.TextElideMode.ElideRight, self.width() - 30
        ))
        self.setToolTip('Selected source channels:\\n' + '\\n'.join(selected))


class CalibrationScreen(QDialog):
    """Fullscreen 60-second calibration prompt. Esc cancels recording."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.started_at = None
        self.setWindowTitle(f'{kind} calibration')
        self.setStyleSheet('background: black; color: white;')
        # Native movable and maximizable window, initially over app plots.
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinMaxButtonsHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(900, 580)
        if parent is not None:
            rect = parent.frameGeometry()
            self.move(rect.center() - self.rect().center())
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.instruction = QLabel('Close your eyes' if kind == 'EYC' else 'Look at the dot')
        self.instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.instruction.setStyleSheet('font-size: 52px; color: white;')
        layout.addWidget(self.instruction)
        if kind == 'BSL':
            self.fixation = QLabel('•')
            self.fixation.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.fixation.setStyleSheet('font-size: 80px; color: white;')
            layout.addWidget(self.fixation)
        self.clock = QLabel('')
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock.setStyleSheet('font-size: 22px; color: #aaa;')
        layout.addWidget(self.clock)
        cancel = QPushButton('Cancel (Esc)')
        cancel.setFixedWidth(160)
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignCenter)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)

    def showEvent(self, event):
        super().showEvent(event)
        self.started_at = time.monotonic()
        self.timer.start()

    def tick(self):
        remaining = max(0, DURATION_SECONDS - (time.monotonic() - self.started_at))
        self.clock.setText(f'{remaining:.0f} s remaining')
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
        self.stream_buttons = {}
        self.channel_metadata_cache = {}
        self.plots, self.curves = {}, {}
        self.raw_history = {k: deque() for k in ('EEG', 'EDA', 'PPG')}
        self.raw_view_seconds = 5.0
        self.raw_follow_live = True
        self.raw_plot_origin = None
        self.raw_latest_time = None
        self.raw_last_sample = {}
        self.raw_last_received_at = None
        self.raw_clock = SmoothViewportClock()
        self.raw_scale = {}
        self.raw_dirty = True
        self.metric_dirty = True
        self.raw_last_render_time = 0.0
        self.metric_labels, self.metric_status = {}, {}
        self.pending = {}
        self.capture = None
        self.loaded_eyc = None
        self.loaded_bsl = None
        self.calibration_paths = {'EYC': None, 'BSL': None}
        self.latest_metrics = {}
        self.ei_estimator = BaselineEmotionalIndex()
        self.metric_keys = [('EEG', 'AWI'), ('EEG', 'BAR'), ('EDA', 'SCL'),
                            ('PPG', 'HR'), ('EI', 'EI')]
        self.metric_history = {key: deque(maxlen=900) for key in self.metric_keys}
        self.metric_plot_origin = time.monotonic()
        self.metric_view_seconds = 5.0
        self.metric_follow_live = True
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
            button = QPushButton('▶ Play')
            button.setToolTip(f'Start/stop local {kind} LSL reception (not the publisher)')
            button.clicked.connect(lambda _, k=kind: self.toggle_stream(k))
            self.stream_buttons[kind] = button
            controls.addWidget(button)
        refresh = QPushButton('Refresh LSL')
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.tab_changed)
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
        visibility.addWidget(QLabel('Time window'))
        self.raw_time_window = QComboBox()
        for label, seconds in (
            ('5 s', 5), ('10 s', 10), ('30 s', 30),
            ('1 min', 60), ('5 min', 300),
        ):
            self.raw_time_window.addItem(label, seconds)
        self.raw_time_window.currentIndexChanged.connect(self.set_raw_time_window)
        visibility.addWidget(self.raw_time_window)
        raw_zoom_in = QPushButton('Zoom +')
        raw_zoom_in.clicked.connect(lambda: self.zoom_raw_plots(0.5))
        visibility.addWidget(raw_zoom_in)
        raw_zoom_out = QPushButton('Zoom −')
        raw_zoom_out.clicked.connect(lambda: self.zoom_raw_plots(2.0))
        visibility.addWidget(raw_zoom_out)
        self.raw_live_button = QPushButton('● LIVE — following')
        self.raw_live_button.clicked.connect(self.resume_raw_live)
        self.raw_live_button.setEnabled(False)
        self.raw_live_button.setToolTip('Live samples stay at the right edge; dragging the plot pauses following')
        visibility.addWidget(self.raw_live_button)
        signals_layout.addWidget(QLabel(
            'Solid = raw; dashed = processed. Both use the same per-channel display scaling.'
        ))
        for kind in ('EEG', 'EDA', 'PPG'):
            plot = pg.PlotWidget(title=f'{kind} — 5 s view, 5 min history')
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setLabel('bottom', 'Elapsed session time', 's')
            plot.getViewBox().sigRangeChangedManually.connect(
                lambda *args, k=kind: self.raw_view_changed_manually(k)
            )
            plot.setXRange(-5, 0, padding=0)
            plot.setMinimumHeight(350 if kind == 'EEG' else 300)
            plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            signals_layout.addWidget(plot)
            self.plots[kind] = plot
            self.curves[kind] = []
        signals_scroll = QScrollArea()
        signals_scroll.setWidgetResizable(True)
        signals_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        signals_scroll.setWidget(signals_page)
        self.tabs.addTab(signals_scroll, 'Raw Data')

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
        calibration_row = QHBoxLayout()
        calibration_row.addWidget(QLabel('Calibration files:'))
        self.calibration_file_labels = {}
        for calibration_kind in ('EYC', 'BSL'):
            select_file = QPushButton(f'Load {calibration_kind}…')
            select_file.clicked.connect(
                lambda _, k=calibration_kind: self.load_existing(k)
            )
            calibration_row.addWidget(select_file)
            file_label = QLabel('None selected')
            file_label.setToolTip(f'No {calibration_kind} file loaded')
            calibration_row.addWidget(file_label)
            self.calibration_file_labels[calibration_kind] = file_label
        calibration_row.addStretch()
        metrics_layout.addLayout(calibration_row)
        self.calibration_state = QLabel('EYC: none (default IAF 10 Hz) | BSL: none')
        metrics_layout.addWidget(self.calibration_state)
        metric_visibility = QHBoxLayout()
        metric_visibility.addWidget(QLabel('Plot metrics:'))
        self.metric_checks = {}
        for key in self.metric_keys:
            checkbox = QCheckBox(key[1])
            checkbox.setChecked(True)
            checkbox.toggled.connect(self.refresh_metric_plot)
            self.metric_checks[key] = checkbox
            metric_visibility.addWidget(checkbox)
        metric_visibility.addStretch()
        metrics_layout.addLayout(metric_visibility)
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel('Time window'))
        self.metric_time_window = QComboBox()
        for label, seconds in (
            ('5 s', 5), ('10 s', 10), ('30 s', 30),
            ('1 min', 60), ('5 min', 300),
        ):
            self.metric_time_window.addItem(label, seconds)
        self.metric_time_window.currentIndexChanged.connect(self.set_metric_time_window)
        zoom_row.addWidget(self.metric_time_window)
        zoom_in = QPushButton('Zoom +')
        zoom_in.clicked.connect(lambda: self.zoom_metric_plot(0.5))
        zoom_row.addWidget(zoom_in)
        zoom_out = QPushButton('Zoom −')
        zoom_out.clicked.connect(lambda: self.zoom_metric_plot(2.0))
        zoom_row.addWidget(zoom_out)
        self.metric_live_button = QPushButton('● LIVE — following')
        self.metric_live_button.clicked.connect(self.resume_metric_live)
        zoom_row.addWidget(self.metric_live_button)
        zoom_row.addStretch()
        metrics_layout.addLayout(zoom_row)
        processing_row = QHBoxLayout()
        processing_row.addWidget(QLabel('Smoothing'))
        self.metric_smoothing = QComboBox()
        for label, value in (
            ('None', 'none'), ('Moving average', 'mean'),
            ('Exponential (EMA)', 'ema'), ('Moving median', 'median')
        ):
            self.metric_smoothing.addItem(label, value)
        self.metric_smoothing.currentIndexChanged.connect(self.refresh_metric_plot)
        processing_row.addWidget(self.metric_smoothing)
        processing_row.addWidget(QLabel('Duration'))
        self.metric_smoothing_duration = QComboBox()
        for duration in (1, 2, 3, 5, 10):
            self.metric_smoothing_duration.addItem(f'{duration} s', float(duration))
        self.metric_smoothing_duration.setCurrentIndex(1)
        self.metric_smoothing_duration.setEnabled(False)
        self.metric_smoothing_duration.currentIndexChanged.connect(self.refresh_metric_plot)
        processing_row.addWidget(self.metric_smoothing_duration)
        self.metric_smoothing.currentIndexChanged.connect(
            lambda: self.metric_smoothing_duration.setEnabled(
                self.metric_smoothing.currentData() != 'none'
            )
        )
        processing_row.addWidget(QLabel('Interpolation'))
        self.metric_interpolation = QComboBox()
        for label, value in (
            ('None (points)', 'none'), ('Linear', 'linear'),
            ('PCHIP', 'pchip'), ('Cubic spline', 'cubic')
        ):
            self.metric_interpolation.addItem(label, value)
        self.metric_interpolation.setCurrentIndex(2)
        self.metric_interpolation.currentIndexChanged.connect(self.refresh_metric_plot)
        processing_row.addWidget(self.metric_interpolation)
        self.metric_sample_markers = QCheckBox('Measured points')
        self.metric_sample_markers.setChecked(True)
        self.metric_sample_markers.toggled.connect(self.refresh_metric_plot)
        processing_row.addWidget(self.metric_sample_markers)
        processing_row.addStretch()
        metrics_layout.addLayout(processing_row)
        self.metric_plot = pg.PlotWidget(title='Combined live metrics — 5 s default, up to 5 min history')
        self.metric_plot.setLabel('bottom', 'Elapsed session time', units='s')
        self.metric_plot.showGrid(x=True, y=True, alpha=.2)
        self.metric_plot.addLegend()
        self.metric_plot.setMouseEnabled(x=True, y=True)
        self.metric_plot.getViewBox().sigRangeChangedManually.connect(
            self.metric_view_changed_manually
        )
        self.metric_curves = {}
        self.metric_point_curves = {}
        for key, color in zip(self.metric_keys, (
            '#e69f00', '#56b4e9', '#009e73', '#cc79a7', '#d55e00'
        )):
            self.metric_curves[key] = self.metric_plot.plot(
                name=f'{key[0]} / {key[1]}', pen=pg.mkPen(color, width=2),
                connect='finite',
            )
            self.metric_point_curves[key] = self.metric_plot.plot(
                pen=None, symbol='o', symbolSize=5,
                symbolBrush=pg.mkBrush(color), symbolPen=None,
            )
        self.metric_plot.setMinimumHeight(520)
        self.metric_plot.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        metrics_layout.addWidget(self.metric_plot)
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
        metrics_scroll = QScrollArea()
        metrics_scroll.setWidgetResizable(True)
        metrics_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        metrics_scroll.setWidget(metrics_page)
        self.tabs.addTab(metrics_scroll, 'Metrics')

        self.statusBar().showMessage('Start an LSL source, then press Refresh LSL.')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.render_frame)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.start(33)
        self.refresh()

    def refresh(self):
        try:
            streams = discover()
            self.channel_metadata_cache.clear()
            for kind, combo in self.selectors.items():
                old = combo.currentData()
                uid = old.uid() if old is not None else None
                combo.blockSignals(True)
                combo.clear()
                for info in streams:
                    combo.addItem(
                        f'{info.name()} [{info.type()}] '
                        f'({info.channel_count()} ch, {info.nominal_srate():g} Hz)',
                        info
                    )
                if uid is not None:
                    for idx in range(combo.count()):
                        if combo.itemData(idx).uid() == uid:
                            combo.setCurrentIndex(idx)
                            break
                combo.blockSignals(False)
                self.stream_selection_changed(kind)
            self.statusBar().showMessage(f'Found {len(streams)} LSL streams')
        except Exception as exc:
            self.statusBar().showMessage(str(exc))

    def stream_selection_changed(self, kind):
        info = self.selectors[kind].currentData()
        if info is None:
            self.channel_selectors[kind].set_channels([])
            return
        identifier = info.uid()
        if identifier not in self.channel_metadata_cache:
            try:
                self.channel_metadata_cache[identifier] = full_channel_labels(info)
            except Exception as exc:
                self.channel_metadata_cache[identifier] = (
                    channel_labels(info),
                    f'Unable to fetch full LSL channel metadata: {exc}',
                )
        labels, warning = self.channel_metadata_cache[identifier]
        self.channel_selectors[kind].set_channels(labels)
        if warning:
            self.statusBar().showMessage(warning)

    def toggle_stream(self, kind):
        worker = self.workers.get(kind)
        if worker is not None and worker.isRunning():
            self.stop_stream(kind)
        else:
            self.connect_stream(kind)

    def reset_stream_display(self, kind):
        self.pending.pop(kind, None)
        self.raw_history[kind].clear()
        self.raw_last_sample.pop(kind, None)
        if not self.raw_last_sample:
            self.raw_clock.reset()
            self.raw_plot_origin = None
            self.raw_latest_time = None
            self.raw_last_received_at = None
        self.raw_scale.pop(kind, None)
        self.raw_dirty = True
        self.latest_metrics.pop(kind, None)
        for key in self.metric_keys:
            if key[0] == kind:
                self.metric_history[key].clear()
        plot = self.plots[kind]
        plot.clear()
        self.curves[kind] = []
        if kind in ('EDA', 'PPG'):
            self.ei_estimator.latest.clear()
            self.metric_history[('EI', 'EI')].clear()
            self.latest_metrics.pop('EI', None)
        self.refresh_metrics()

    def stop_stream(self, kind):
        if self.capture is not None:
            QMessageBox.warning(self, 'Calibration in progress',
                                'Finish or cancel the calibration before stopping a stream.')
            return
        worker = self.workers.get(kind)
        if worker is None:
            self.stream_buttons[kind].setText('▶ Play')
            return
        self.stream_buttons[kind].setEnabled(False)
        self.stream_buttons[kind].setText('Stopping…')
        stopped = worker.stop()
        if stopped:
            self.workers.pop(kind, None)
            self.stream_buttons[kind].setEnabled(True)
            self.stream_buttons[kind].setText('▶ Play')
            self.reset_stream_display(kind)
            self.statusBar().showMessage(
                f'{kind} reception stopped (LSL source is still transmitting)'
            )
        else:
            self.statusBar().showMessage(f'{kind}: waiting for receiver to stop')

    def receiver_finished(self, kind, worker):
        if self.workers.get(kind) is not worker:
            return
        self.workers.pop(kind, None)
        self.stream_buttons[kind].setEnabled(True)
        self.stream_buttons[kind].setText('▶ Play')
        self.reset_stream_display(kind)
        if worker.active:
            self.statusBar().showMessage(f'{kind} receiver ended unexpectedly')
        else:
            self.statusBar().showMessage(f'{kind} reception stopped')

    def connect_stream(self, kind):
        if self.capture is not None:
            QMessageBox.warning(self, 'Calibration in progress',
                                'Finish or cancel calibration before changing a stream.')
            return
        info = self.selectors[kind].currentData()
        if info is None:
            self.statusBar().showMessage(f'No {kind} stream selected')
            return
        try:
            indices = validated_indices(
                self.channel_selectors[kind].selected_indices(),
                info.channel_count(), kind,
            )
            previous = self.workers.get(kind)
            if previous is not None and previous.isRunning():
                QMessageBox.warning(self, 'Receiver active',
                                    f'Stop {kind} before starting another stream.')
                return
            worker = Receiver(info, kind, indices, self.channel_selectors[kind].names)
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, f'{kind} channel selection', str(exc))
            return
        self.reset_stream_display(kind)
        worker.updated.connect(self.receive)
        worker.samples_received.connect(self.capture_samples)
        worker.stream_ready.connect(self.ready_stream)
        worker.iaf_hz = self.iaf_hz
        worker.failure.connect(self.statusBar().showMessage)
        worker.finished.connect(lambda k=kind, w=worker: self.receiver_finished(k, w))
        self.workers[kind] = worker
        self.stream_buttons[kind].setText('■ Stop')
        worker.start()
        self.statusBar().showMessage(f'{kind}: starting selected LSL stream reception')

    def receive(self, kind, raw, processed, names, metric, fs, timestamps):
        self.append_raw_chunk(kind, raw, processed, names, fs, timestamps)
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
                'status': 'EI from HR/GSR z-scores against BSL'
                if value is not None else 'EI needs valid BSL HR/SCL references and fresh signals',
            }
            self.metric_history[('EI', 'EI')].append(
                (now, float(value) if value is not None else float('nan'))
            )
        self.refresh_metric_labels()
        self.metric_dirty = True

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
        self.refresh_metric_labels()
        self.metric_dirty = True

    def refresh_metric_labels(self):
        for (kind, name), label in self.metric_labels.items():
            raw = self.latest_metrics.get(kind, {}).get(name)
            value = self.displayed_value(kind, name, raw)
            label.setText(f'{name}: {value:.3f}' if value is not None else f'{name}: —')
        for kind, label in self.metric_status.items():
            label.setText(self.latest_metrics.get(kind, {}).get('status', 'Waiting for data'))

    def set_metric_time_window(self, *_):
        seconds = self.metric_time_window.currentData()
        if seconds is None:
            return
        self.metric_view_seconds = float(seconds)
        self.resume_metric_live()

    def zoom_metric_plot(self, scale):
        self.metric_view_seconds = float(np.clip(
            self.metric_view_seconds * scale, 1.0, 300.0
        ))
        self.metric_time_window.blockSignals(True)
        idx = self.metric_time_window.findData(int(self.metric_view_seconds))
        self.metric_time_window.setCurrentIndex(idx)
        self.metric_time_window.blockSignals(False)
        self.resume_metric_live()

    def resume_metric_live(self):
        self.metric_follow_live = True
        self.metric_live_button.setText('● LIVE — following')
        self.metric_live_button.setEnabled(False)
        self.update_metric_xrange()

    def metric_view_changed_manually(self, *_):
        xlow, xhigh = self.metric_plot.viewRange()[0]
        span = float(max(.01, xhigh - xlow))
        is_zoom = abs(span - self.metric_view_seconds) > max(.001, .001*self.metric_view_seconds)
        was_following = self.metric_follow_live
        self.metric_view_seconds = span
        if was_following and is_zoom:
            self.update_metric_xrange()
        else:
            self.metric_follow_live = False
            self.metric_live_button.setText('▶ Resume live (paused)')
            self.metric_live_button.setEnabled(True)

    def update_metric_xrange(self):
        if self.metric_follow_live:
            elapsed = time.monotonic() - self.metric_plot_origin
            self.metric_plot.setXRange(
                elapsed - self.metric_view_seconds, elapsed, padding=0
            )

    def refresh_metric_plot(self, *_):
        now = time.monotonic()
        method = self.metric_smoothing.currentData()
        duration = self.metric_smoothing_duration.currentData()
        interpolation = self.metric_interpolation.currentData()
        show_markers = self.metric_sample_markers.isChecked()
        for (kind, name), curve in self.metric_curves.items():
            key = (kind, name)
            visible = self.metric_checks[key].isChecked()
            curve.setVisible(visible)
            markers = self.metric_point_curves[key]
            markers.setVisible(visible and (show_markers or interpolation == 'none'))
            if not visible:
                continue
            points = [(t, val) for t, val in self.metric_history[key]
                      if now - t <= 300]
            if not points:
                curve.clear()
                markers.clear()
                continue
            timestamps = np.asarray(
                [t - self.metric_plot_origin for t, _ in points], dtype=float
            )
            display = [self.displayed_value(kind, name, val) for _, val in points]
            values = np.asarray(
                [float(v) if v is not None else np.nan for v in display],
                dtype=float,
            )
            x, y, measured_x, measured_y = prepare_metric_curve(
                timestamps, values,
                smoothing=method, seconds=float(duration),
                interpolation=interpolation, display_hz=20.0,
                max_gap=1.1,
            )
            if interpolation == 'none':
                curve.clear()
            else:
                curve.setData(x, y, connect='finite')
            if show_markers or interpolation == 'none':
                markers.setData(measured_x, measured_y)
        self.metric_dirty = False

    def append_raw_chunk(self, kind, raw, processed, names, fs, timestamps):
        # The worker passes the actual LSL timestamps along with exactly
        # corresponding raw/filtered samples. Arrival time varies with
        # thread scheduling and MUST NOT determine sample positions.
        t, raw, processed = clean_lsl_chunk(
            timestamps, raw, processed, self.raw_last_sample.get(kind)
        )
        if not len(t):
            return
        self.raw_last_sample[kind] = float(t[-1])
        if self.raw_plot_origin is None:
            self.raw_plot_origin = float(t[0])
        self.raw_history[kind].append(
            (t, raw.copy(), processed.copy(), list(names), float(fs))
        )
        if self.raw_latest_time is None or float(t[-1]) > self.raw_latest_time:
            self.raw_latest_time = float(t[-1])
            self.raw_last_received_at = time.monotonic()
            self.raw_clock.observe(self.raw_latest_time, self.raw_last_received_at)
        self.raw_dirty = True
        cutoff = self.raw_latest_time - 300.0
        chunks = self.raw_history[kind]
        while chunks and chunks[0][0][-1] < cutoff:
            chunks.popleft()

    def set_raw_time_window(self, *_):
        seconds = self.raw_time_window.currentData()
        if seconds is not None:
            self.raw_view_seconds = float(seconds)
            self.resume_raw_live()

    def zoom_raw_plots(self, factor):
        self.raw_view_seconds = float(np.clip(
            self.raw_view_seconds * factor, 1.0, 300.0
        ))
        self.raw_time_window.blockSignals(True)
        index = self.raw_time_window.findData(int(self.raw_view_seconds))
        self.raw_time_window.setCurrentIndex(index)
        self.raw_time_window.blockSignals(False)
        self.resume_raw_live()

    def resume_raw_live(self):
        self.raw_follow_live = True
        self.raw_live_button.setText('● LIVE — following')
        self.raw_live_button.setEnabled(False)
        self.update_raw_xranges()
        self.draw()

    def raw_view_changed_manually(self, kind, *_):
        low, high = self.plots[kind].viewRange()[0]
        span = float(max(.01, high - low))
        was_following = self.raw_follow_live
        # A wheel zoom changes the width of the time axis; it should
        # NOT freeze live acquisition. Horizontal dragging translates the
        # viewport without changing its width and deliberately pauses it.
        is_zoom = abs(span - self.raw_view_seconds) > max(.001, .001*self.raw_view_seconds)
        self.raw_view_seconds = span
        if was_following and is_zoom:
            self.update_raw_xranges()
        else:
            self.raw_follow_live = False
            self.raw_live_button.setText('▶ Resume live (paused)')
            self.raw_live_button.setEnabled(True)
            for other, plot in self.plots.items():
                if other != kind:
                    plot.setXRange(low, high, padding=0)
        self.draw()

    def update_raw_xranges(self):
        if not self.raw_follow_live or self.raw_plot_origin is None:
            return
        head = self.raw_clock.advance(time.monotonic())
        if head is None:
            return
        end = head - self.raw_plot_origin
        for plot in self.plots.values():
            plot.setXRange(end - self.raw_view_seconds, end, padding=0)

    def tab_changed(self, index):
        if index == 0:
            self.raw_dirty = True
            self.draw()
        elif index == 1:
            self.metric_dirty = True
            self.refresh_metric_plot()

    def render_frame(self):
        # Animation is independent of data acquisition and analysis cadence.
        if self.tabs.currentIndex() == 0:
            self.update_raw_xranges()
            if self.raw_dirty and time.monotonic() - self.raw_last_render_time >= 0.10:
                self.draw()
        elif self.tabs.currentIndex() == 1:
            self.update_metric_xrange()
            if self.metric_dirty:
                self.refresh_metric_plot()

    def draw(self):
        if self.tabs.currentIndex() != 0:
            return
        self.raw_dirty = False
        self.raw_last_render_time = time.monotonic()
        for kind, chunks in self.raw_history.items():
            if not chunks:
                continue
            plot = self.plots[kind]
            low, high = plot.viewRange()[0]
            times, raw_parts, filtered_parts = [], [], []
            names = chunks[-1][3]
            # Iterate backwards from the newest chunk, stopping once
            # history is older than the viewport. Never scan all five
            # retained minutes for a five-second view.
            t_min = self.raw_plot_origin + low
            t_max = self.raw_plot_origin + high
            selected = []
            for item in reversed(chunks):
                stamps = item[0]
                if stamps[-1] < t_min:
                    break
                if stamps[0] <= t_max:
                    selected.append(item)
            for stamps, raw, filtered, _, fs in reversed(selected):
                visible_t, visible_raw, visible_filtered = visible_chunk(
                    stamps, raw, filtered, t_min, t_max
                )
                if not len(visible_t):
                    continue
                times.append(visible_t - self.raw_plot_origin)
                raw_parts.append(visible_raw)
                filtered_parts.append(visible_filtered)
            if not times:
                for curve in self.curves[kind]:
                    curve.clear()
                continue
            t = np.concatenate(times)
            raw = np.concatenate(raw_parts)
            filtered = np.concatenate(filtered_parts)
            stride = max(1, int(np.ceil(len(t) / 5000)))
            t, raw, filtered = t[::stride], raw[::stride], filtered[::stride]
            n = min(raw.shape[1], 8 if kind == 'EEG' else 1)
            if len(self.curves[kind]) != 2*n:
                plot.clear()
                self.curves[kind] = []
                plot.enableAutoRange(axis='y', enable=False)
                plot.setYRange(-3., n*6., padding=0)
                for i in range(n):
                    color = pg.intColor(i, hues=max(n, 3))
                    self.curves[kind].append(plot.plot(
                        name=f'{names[i]} raw', pen=pg.mkPen(color, width=1)
                    ))
                    self.curves[kind].append(plot.plot(
                        name=f'{names[i]} processed',
                        pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine)
                    ))
            # Anchor both raw and processed curves to the same robust
            # scaling reference, established once for the stream. Avoid
            # artificial movement from recomputing median/std each frame.
            if kind not in self.raw_scale:
                # Wait for a meaningful fraction of a second before
                # freezing scaling; first LSL chunks may have 1-5 samples.
                fs = chunks[-1][4]
                if len(raw) < max(8, round(fs * .75)):
                    continue
                centers = np.median(raw[:, :n], axis=0)
                spreads = np.std(raw[:, :n], axis=0)
                spreads = np.where(np.isfinite(spreads) & (spreads > 1e-12),
                                   spreads, 1.)
                self.raw_scale[kind] = (centers, spreads)
            centers, spreads = self.raw_scale[kind]
            for i in range(n):
                r, p = raw[:, i], filtered[:, i]
                if self.show_raw.isChecked():
                    self.curves[kind][2*i].setData(
                        t, (r-centers[i])/spreads[i] + i*6
                    )
                else:
                    self.curves[kind][2*i].clear()
                if self.show_processed.isChecked():
                    self.curves[kind][2*i+1].setData(
                        t, (p-centers[i])/spreads[i] + i*6
                    )
                else:
                    self.curves[kind][2*i+1].clear()


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
            channels = list(worker.selected_names)
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
        except Exception as exc:
            QMessageBox.critical(self, 'Save failed', str(exc))
            return
        # Once the file is written, a display/UI exception is not a
        # calibration save failure. Keep the saved file and report separately.
        try:
            self.apply_calibration(kind, {'analysis': analysis}, filename=filename)
        except Exception as exc:
            self.statusBar().showMessage(f'Saved {kind}: {filename}')
            QMessageBox.warning(
                self, 'Calibration saved; display update failed',
                f'{kind} was saved successfully to:\n{filename}\n\n'
                f'The interface could not refresh: {exc}'
            )
            return
        self.statusBar().showMessage(f'Saved {kind}: {filename}')

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

    def apply_calibration(self, kind, meta, filename=None):
        if kind == 'EYC':
            self.loaded_eyc = meta
            self.iaf_hz = float(meta['analysis']['iaf_hz'])
            for worker in self.workers.values():
                if worker.kind == 'EEG':
                    worker.iaf_hz = self.iaf_hz
        else:
            self.loaded_bsl = meta
            references = (meta.get('analysis') or {}).get('metrics', {})
            self.ei_estimator.set_references(
                references.get('PPG', {}).get('HR'),
                references.get('EDA', {}).get('SCL'),
            )
        self.calibration_paths[kind] = filename
        file_label = self.calibration_file_labels[kind]
        file_label.setText(Path(filename).name if filename else 'Loaded (unsaved)')
        file_label.setToolTip(filename or 'Calibration active but not saved to a file')
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
            # EI_matrix changed to the MATLAB axis/quadrant convention.
            # Reanalyze saved BSL recordings to avoid using historical EI
            # reference statistics computed with the old angular formula.
            # EYC is unchanged and can use its saved result.
            analysis = (self.analyze_calibration(kind, streams)
                        if kind == 'BSL'
                        else meta.get('analysis') or self.analyze_calibration(kind, streams))
            self.inspect_calibration(kind, analysis)
            self.apply_calibration(kind, {'analysis': analysis}, filename=filename)
            self.statusBar().showMessage(f'Loaded {kind}: {filename}')
        except Exception as exc:
            QMessageBox.critical(self, f'Cannot load {kind}', str(exc))

    def closeEvent(self, event):
        for worker in self.workers.values():
            worker.stop()
        super().closeEvent(event)
