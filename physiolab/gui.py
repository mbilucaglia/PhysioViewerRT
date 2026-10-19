import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QGridLayout
)
from PySide6.QtCore import QTimer
from .worker import Receiver, discover


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PhysioViewerRT — local LSL monitor')
        self.resize(1200, 850)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        top = QHBoxLayout()
        layout.addLayout(top)
        self.selectors = {}
        self.workers = {}
        self.plots = {}
        self.curves = {}
        self.metrics = {}
        self.pending = {}
        for kind in ('EEG', 'EDA', 'PPG'):
            top.addWidget(QLabel(kind))
            combo = QComboBox()
            combo.setMinimumWidth(175)
            top.addWidget(combo)
            self.selectors[kind] = combo
            button = QPushButton('Connect')
            button.clicked.connect(lambda _, k=kind: self.connect_stream(k))
            top.addWidget(button)
        refresh = QPushButton('Refresh LSL')
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        grid = QGridLayout()
        layout.addLayout(grid)
        for i, kind in enumerate(('EEG', 'EDA', 'PPG')):
            panel = QVBoxLayout()
            label = QLabel(f'{kind}: waiting')
            panel.addWidget(label)
            self.metrics[kind] = label
            plot = pg.PlotWidget(title=f'{kind} — filtered signal (last 5 s)')
            plot.showGrid(x=True, y=True, alpha=.2)
            panel.addWidget(plot)
            self.plots[kind] = plot
            self.curves[kind] = []
            grid.addLayout(panel, i, 0)
        self.statusBar().showMessage('Ready. Start an LSL source and press Refresh LSL.')
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
                    if kind == 'EDA':
                        matching = info.type().upper() in ('EDA', 'GSR')
                    else:
                        matching = info.type().upper() == kind
                    if matching:
                        combo.addItem(
                            f'{info.name()} ({info.channel_count()} ch, {info.nominal_srate():g} Hz)', info
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
        worker = Receiver(info, kind)
        worker.updated.connect(self.receive)
        worker.failure.connect(self.statusBar().showMessage)
        self.workers[kind] = worker
        worker.start()

    def receive(self, kind, data, names, metric):
        self.pending[kind] = (data, names)
        if metric is not None:
            vals = ', '.join(
                f'{k}: {v:.3f}' if isinstance(v, (float, int)) else f'{k}: {v}'
                for k, v in metric.items()
            )
            self.metrics[kind].setText(f'{kind} — {vals}')

    def draw(self):
        for kind, (data, names) in list(self.pending.items()):
            plot = self.plots[kind]
            n = min(data.shape[1], 8 if kind == 'EEG' else 2)
            if len(self.curves[kind]) != n:
                plot.clear()
                self.curves[kind] = [
                    plot.plot(pen=pg.mkPen(pg.intColor(i, hues=max(n, 3)), width=1))
                    for i in range(n)
                ]
            for i, curve in enumerate(self.curves[kind]):
                y = data[:, i]
                scale = np.std(y) or 1.0
                curve.setData(np.arange(len(y)), (y - np.mean(y)) / scale + i * 5)
            self.pending.pop(kind, None)

    def closeEvent(self, event):
        for worker in self.workers.values():
            worker.stop()
        super().closeEvent(event)
