"""Local two-tab biosignal monitor: waveforms and metrics."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QGridLayout, QTabWidget, QCheckBox
)
from .worker import Receiver, discover


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
        self.selectors, self.workers = {}, {}
        self.plots, self.curves = {}, {}
        self.metric_labels, self.metric_status = {}, {}
        self.pending = {}

        for kind in ('EEG', 'EDA', 'PPG'):
            controls.addWidget(QLabel(kind))
            combo = QComboBox()
            combo.setMinimumWidth(160)
            self.selectors[kind] = combo
            controls.addWidget(combo)
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
        metrics_grid = QGridLayout(metrics_page)
        for row, (kind, keys) in enumerate((
            ('EEG', ('FAA', 'alpha_left', 'alpha_right')),
            ('EDA', ('SCL',)),
            ('PPG', ('HR',)),
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
        worker = Receiver(info, kind)
        worker.updated.connect(self.receive)
        worker.failure.connect(self.statusBar().showMessage)
        self.workers[kind] = worker
        worker.start()

    def receive(self, kind, raw, processed, names, metric, fs):
        self.pending[kind] = (raw, processed, names, fs)
        if metric is not None:
            for (modality, key), label in self.metric_labels.items():
                if modality != kind:
                    continue
                value = metric.get(key)
                label.setText(
                    f'{key}: {value:.3f}' if isinstance(value, (int, float))
                    and np.isfinite(value) else f'{key}: —'
                )
            self.metric_status[kind].setText(metric.get('status', 'Updated (1 s window, 50% overlap)'))

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
                        pen=pg.mkPen(color, width=2, style=__import__('PySide6').QtCore.Qt.DashLine)
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

    def closeEvent(self, event):
        for worker in self.workers.values():
            worker.stop()
        super().closeEvent(event)
