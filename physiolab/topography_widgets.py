"""EEG topography view with one bounded background calculation at a time."""
from concurrent.futures import ThreadPoolExecutor
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QToolButton,
    QDoubleSpinBox, QCheckBox, QDialog, QFormLayout,
)

from .topography import TopographySettings, calculate_topography
from .eeg_montage import MONTAGE_NAME
from .display_units import DEFAULT_EEG_DISPLAY_STEP
from .settings import DEFAULT_VIEWER_SETTINGS


class SmoothTopographyImage(pg.ImageItem):
    def paint(self, painter, *args):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        super().paint(painter, *args)
        painter.restore()


class TopographyView(QWidget):
    def __init__(self, parent=None, extrapolate_control=None, *, colour_controls=None,
                 colour_step=DEFAULT_VIEWER_SETTINGS.gain_step):
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='eeg-topography')
        self._closing = False
        self._future = None
        self._revision = 0
        self._key = None
        self._last_end = None
        self._next_tick = 0.
        self.result = None
        self._sensor_key = None
        self._colour_levels = None
        self._colour_context = None
        self._colour_source_identity = None
        self._colour_step = colour_step
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(3)
        header = QHBoxLayout()
        header.addWidget(QLabel('EEG topoplot'))
        self.band = QComboBox()
        self.band.setObjectName('topographyBand')
        self.band.addItems(['Unfiltered', 'Delta', 'Theta', 'Alpha', 'Beta', 'Gamma'])
        self.band.setCurrentText('Alpha')
        header.addWidget(self.band, 1)
        options = QToolButton()
        options.setObjectName('topographySettings')
        options.setText('…')
        options.setToolTip('Topoplot settings')
        options.setAccessibleName('Topoplot settings')
        header.addWidget(options)
        self.move = QToolButton()
        self.move.setText('Move')
        self.expand = QToolButton()
        self.expand.setText('Expand')
        self.expand.setCheckable(True)
        header.addWidget(self.move)
        header.addWidget(self.expand)
        layout.addLayout(header)
        self.options = QDialog(self)
        self.options.setWindowTitle('EEG topoplot settings')
        form = QFormLayout(self.options)
        if colour_controls is None:
            colour_row = QHBoxLayout()
            colour_controls = {name: QToolButton() for name in ('minus', 'fit', 'plus')}
            for name, text in (('minus', '−'), ('fit', 'Fit'), ('plus', '+')):
                colour_controls[name].setText(text)
                colour_row.addWidget(colour_controls[name])
            colour_controls['auto'] = QCheckBox('Auto')
            colour_controls['auto'].setChecked(True)
            colour_row.addWidget(colour_controls['auto'])
            form.addRow('Colour scale', colour_row)
        self.colour_minus = colour_controls['minus']
        self.colour_fit = colour_controls['fit']
        self.colour_plus = colour_controls['plus']
        self.colour_auto = colour_controls['auto']
        self.extrapolate = extrapolate_control
        if self.extrapolate is None:
            self.extrapolate = QCheckBox('Full scalp · extrapolate beyond electrodes')
            self.extrapolate.setChecked(True)
            form.addRow(self.extrapolate)
        self.source = QComboBox()
        self.source.addItem('Processed EEG', 'processed')
        self.source.addItem('Raw EEG', 'raw')
        form.addRow('Band-power input', self.source)
        self.iaf = QCheckBox('Use calibrated IAF ±2 Hz for Alpha')
        self.iaf.setChecked(True)
        form.addRow(self.iaf)
        self.iaf_status = QLabel('No calibrated IAF · Alpha uses 8–13 Hz')
        form.addRow(self.iaf_status)
        self.window = self._spin(.25, 10., 2., .25, ' s')
        self.overlap = self._spin(0., 95., 50., 5., ' %')
        self.persistence = self._spin(0., 2., .15, .05, ' s')
        self.window.setObjectName('topographyWindow')
        self.overlap.setObjectName('topographyOverlap')
        self.persistence.setObjectName('topographyPersistence')
        form.addRow('Analysis window', self.window)
        form.addRow('Window overlap', self.overlap)
        form.addRow('Unfiltered persistence (τ)', self.persistence)
        explanation = QLabel(
            'Band views show absolute power; unfiltered shows signed raw voltage.\n'
            'Persistence averages recent raw voltages with exponential decay; 0 = latest sample.\n'
            'Update step = window × (1 − overlap). RAW pause freezes the map.\n'
            f'{MONTAGE_NAME} · includes 10-10 and 10-20; template coordinates.\n'
            'Spherical splines give a smooth scalp field; circles mark available channels.\n'
            'Full scalp extrapolates beyond electrode coverage; these regions are estimated.\n'
            'Uncheck Full scalp to limit the map to the area enclosed by electrodes.\n'
            'Uses all selected EEG channels and the source reference. Display settings only.')
        explanation.setWordWrap(True)
        form.addRow(explanation)
        self.options.resize(490, 330)
        options.clicked.connect(self.options.show)
        self.plot = pg.PlotWidget(background='w')
        self.plot.setMinimumSize(100, 90)
        self.plot.hideAxis('left')
        self.plot.hideAxis('bottom')
        self.plot.setAspectLocked(True)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)
        self.plot.setXRange(-1.12, 1.12, padding=0)
        self.plot.setYRange(-1.05, 1.18, padding=0)
        self.image = SmoothTopographyImage(axisOrder='row-major')
        self.plot.addItem(self.image)
        a = np.linspace(0, 2*np.pi, 150)
        self.plot.plot(np.cos(a), np.sin(a), pen=pg.mkPen('#45445e', width=1.5))
        self.plot.plot([-.12, 0., .12], [.99, 1.15, .99], pen=pg.mkPen('#45445e', width=1.5))
        for side in (-1, 1):
            self.plot.plot(side*np.array([1., 1.08, 1.08, 1.]), [.18, .12, -.12, -.18],
                           pen=pg.mkPen('#45445e', width=1.5))
        self.sensors = pg.ScatterPlotItem(
            size=6, symbol='o', pen=pg.mkPen('#262735', width=1.),
            brush=(255, 255, 255, 170), hoverable=True,
            tip=lambda x, y, data: str(data))
        self.sensors.setZValue(1.)
        self.plot.addItem(self.sensors)
        self.colorbar = pg.ColorBarItem(values=(0, 1), interactive=False, width=12)
        self.colorbar.setImageItem(self.image, insert_in=self.plot.getPlotItem())
        layout.addWidget(self.plot, 1)
        self.status = QLabel('Waiting for EEG samples')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('font-size: 10px; color: #56536c;')
        layout.addWidget(self.status)
        for widget in (self.band, self.source):
            widget.currentIndexChanged.connect(self.settings_changed)
        for widget in (self.window, self.overlap, self.persistence):
            widget.valueChanged.connect(self.settings_changed)
        self.iaf.toggled.connect(self.settings_changed)
        self.extrapolate.toggled.connect(self.settings_changed)
        self.colour_minus.clicked.connect(lambda: self.adjust_colours(self._colour_step))
        self.colour_plus.clicked.connect(lambda: self.adjust_colours(1/self._colour_step))
        self.colour_fit.clicked.connect(self.fit_colours)
        self.colour_auto.toggled.connect(self.set_colour_auto)
        self.settings_changed()

    @staticmethod
    def _spin(low, high, value, step, suffix):
        widget = QDoubleSpinBox()
        widget.setRange(low, high)
        widget.setDecimals(2)
        widget.setSingleStep(step)
        widget.setValue(value)
        widget.setSuffix(suffix)
        return widget

    def settings(self):
        return TopographySettings(self.band.currentText(), self.source.currentData(),
                                  self.window.value(), self.overlap.value()/100.,
                                  self.persistence.value(), self.iaf.isChecked(),
                                  self.extrapolate.isChecked())

    def settings_changed(self, *_):
        unfiltered = self.band.currentText() == 'Unfiltered'
        self.persistence.setEnabled(unfiltered)
        self.source.setEnabled(not unfiltered)
        self.iaf.setEnabled(self.band.currentText() == 'Alpha')
        self.reset()

    def reset(self):
        self._revision += 1
        self._key = None
        self._last_end = None
        self._next_tick = 0.
        self.clear('Waiting for EEG samples')

    def clear(self, message):
        self.result = None
        self.image.clear()
        self.sensors.clear()
        self._sensor_key = None
        self.status.setText(message)
        self.status.setToolTip(message)
        for button in (self.colour_minus, self.colour_fit, self.colour_plus):
            button.setEnabled(False)

    def _apply_colour_levels(self):
        if self.result is not None and self._colour_levels is not None:
            # ColorBarItem propagates levels to the linked image immediately,
            # including a paused map. Numerical data and worker state are untouched.
            self.colorbar.setLevels(self._colour_levels)

    def set_colour_auto(self, enabled):
        if enabled and self.result is not None:
            self._colour_levels = tuple(self.result['levels'])
            self._apply_colour_levels()

    def fit_colours(self):
        if self.result is None:
            return
        self.colour_auto.setChecked(False)
        self._colour_levels = tuple(self.result['levels'])
        self._apply_colour_levels()

    def adjust_colours(self, factor):
        if self.result is None or self._colour_levels is None:
            return
        self.colour_auto.setChecked(False)
        maximum = float(np.clip(self._colour_levels[1]*factor, 1e-300, 1e300))
        self._colour_levels = (-maximum if self.result['band'] == 'Unfiltered' else 0., maximum)
        self._apply_colour_levels()

    def tick(self, state, iaf=None):
        if self._closing or not self.isVisible():
            return
        config = self.settings()
        self.iaf_status.setText(f'Calibrated IAF: {iaf:.2f} Hz' if iaf is not None else
                               'No calibrated IAF · Alpha uses 8–13 Hz')
        history = state.visible_history('EEG')
        if not history or state.origin is None:
            if self._key is not None:
                self.reset()
            return
        end = min(state.viewport('EEG')[1] + state.origin, float(history[-1][0][-1]))
        scales = np.asarray(state.display_scales.get('EEG', DEFAULT_EEG_DISPLAY_STEP))
        factors = DEFAULT_EEG_DISPLAY_STEP / scales
        colour_source = (state.signals.generations['EEG'], tuple(factors.ravel()), state.units['EEG'])
        if colour_source != self._colour_source_identity:
            self._colour_levels = None
            self._colour_source_identity = colour_source
        key = (state.signals.generations['EEG'], config, iaf,
               tuple(factors.ravel()), state.units['EEG'], state.paused, state.follow_live,
               end if state.paused or not state.follow_live else None)
        if key != self._key:
            self.reset()
            self._key = key
        if self._future is not None and self._future.done():
            revision, future = self._pending_revision, self._future
            self._future = None
            if revision == self._revision:
                try:
                    self.present(future.result(), config, state.origin, state.paused)
                except Exception as exc:
                    self.clear(str(exc))
        now = time.monotonic()
        if (self._future is not None or now < self._next_tick
                or (self._last_end is not None and abs(end-self._last_end) < config.hop - 1e-8)):
            return
        # Share immutable blocks, bounded by the requested time range. No copying
        # a five-minute recording, and never queue more work behind a running job.
        retained = max(config.window, 5*config.persistence if config.band == 'Unfiltered' else 0.)
        chunks = tuple(c for c in history if c[0][-1] >= end-retained and c[0][0] <= end)
        self._last_end = end
        self._next_tick = now + .05  # Hard presentation budget: at most 20 maps/s.
        self._pending_revision = self._revision
        self._future = self._pool.submit(calculate_topography, chunks, end, config,
                                         factors, state.units['EEG'], iaf)

    def present(self, result, config, origin, paused):
        self.result = result
        signed = result['band'] == 'Unfiltered'
        source = 'raw' if signed else config.source
        colour_context = (result['quantity'], source)
        if self.colour_auto.isChecked() or self._colour_levels is None or colour_context != self._colour_context:
            self._colour_levels = tuple(result['levels'])
        self._colour_context = colour_context
        for button in (self.colour_minus, self.colour_fit, self.colour_plus):
            button.setEnabled(True)
        colors = (['#2166ac', '#67a9cf', '#f7f7f7', '#ef8a62', '#b2182b'] if signed else
                  ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725'])
        cmap = pg.ColorMap(np.linspace(0., 1., len(colors)), [pg.mkColor(c) for c in colors])
        self.colorbar.setColorMap(cmap)
        self.image.setImage(result['grid'], autoLevels=False, levels=self._colour_levels)
        self.image.setRect(QRectF(-1., -1., 2., 2.))
        self._apply_colour_levels()
        estimated = result['extrapolated']
        sensor_key = (tuple(result['labels']), tuple(result['positions']))
        if sensor_key != self._sensor_key:
            xy = np.asarray(result['positions'])
            self.sensors.setData(xy[:, 0], xy[:, 1], data=result['labels'])
            self._sensor_key = sensor_key
        summary = (f'{result["quantity"]} · {source} · t={result["end"]-origin:.2f} s\n'
                   f'{len(result["labels"])} electrodes · step {config.hop:g} s'
                   + (' · spline extrapolation' if estimated.any() else ' · spherical spline')
                   + (' · paused' if paused else '')
                   + (f' · excluded {len(result["excluded"])}' if result['excluded'] else ''))
        self.status.setText(summary)
        self.status.setToolTip(summary + f'\n{MONTAGE_NAME} · source reference retained'
                               + '\nSpherical-spline field; circles mark available channels (hover for names).'
                               + '\nFull-scalp areas outside electrode coverage are estimates; no synthetic channels.'
                               + '\nExcluded: ' + (', '.join(result['excluded']) or 'none'))

    def shutdown(self):
        if self._closing:
            return
        self._closing = True
        self._revision += 1
        self._pool.shutdown(wait=False, cancel_futures=True)

    def shutdown_complete(self):
        if self._future is not None and not self._future.done():
            return False
        # No numerical call remains: join only the idle executor's teardown.
        self._pool.shutdown(wait=True, cancel_futures=True)
        return True
