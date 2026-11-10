"""EEG topography view with one bounded background calculation at a time."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QDir, QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QLinearGradient, QPainter, QPen
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QComboBox, QToolButton, QSizePolicy,
    QDoubleSpinBox, QCheckBox,
)

from .topography import TopographySettings, calculate_topography
from .display_units import DEFAULT_EEG_DISPLAY_STEP
from .ui_icons import set_panel_expanded

DESIGNER_DIRECTORY = Path(__file__).resolve().parent.parent / 'designer'
TOPOGRAPHY_UI_PATH = DESIGNER_DIRECTORY / 'TopographyView.ui'
TOPOGRAPHY_PALETTE = ('#440154', '#3b528b', '#21918c', '#5ec962', '#fde725')
ANALYSIS_WINDOW_SECONDS = 1.0
ANALYSIS_OVERLAP = 0.5


class SmoothTopographyImage(pg.ImageItem):
    def paint(self, painter, *args):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        super().paint(painter, *args)
        painter.restore()


class TopographyColorScale(QWidget):
    """Compact vertical color scale in its own gutter beside the scalp."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._levels = (0., 1.)
        self._colors = [pg.mkColor(color) for color in TOPOGRAPHY_PALETTE]
        self.setFixedWidth(58)
        self.setMinimumHeight(90)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setToolTip('Topoplot color scale')

    def levels(self):
        return self._levels

    def setLevels(self, levels):
        levels = tuple(float(value) for value in levels)
        if levels == self._levels:
            return
        self._levels = levels
        self.update()

    def setColors(self, colors):
        colors = [pg.mkColor(color) for color in colors]
        if colors == self._colors:
            return
        self._colors = colors
        self.update()

    @staticmethod
    def _number(value):
        if abs(value) < 1e-14:
            return '0'
        return f'{value:.3g}'

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = painter.font()
        font.setPointSizeF(8.)
        painter.setFont(font)
        painter.setPen(QPen(pg.mkColor('#77768f')))

        top, bottom = 4., float(self.height() - 12)
        if bottom <= top:
            return
        left, bar_width = 4., 9.
        gradient = QLinearGradient(0., bottom, 0., top)
        count = max(2, len(self._colors))
        for index, color in enumerate(self._colors):
            gradient.setColorAt(index / (count - 1), color)
        painter.setPen(QPen(pg.mkColor('#dfe1ef'), .7))
        painter.setBrush(gradient)
        painter.drawRoundedRect(QRectF(left, top, bar_width, bottom - top), 2., 2.)

        low, high = self._levels
        middle = 0. if low < 0. < high else (low + high) / 2.
        ticks = ((high, top), (middle, (top + bottom) / 2.), (low, bottom))
        painter.setPen(QPen(pg.mkColor('#a2a0b2'), .7))
        for value, y in ticks:
            painter.drawLine(QLineF(QPointF(13., y), QPointF(16., y)))
        painter.setPen(QPen(pg.mkColor('#77768f')))
        labels = (self._number(high), self._number(middle), self._number(low))
        for label, y in zip(labels, (top, (top + bottom) / 2., bottom)):
            painter.drawText(18, int(y - 7), self.width() - 18, 14,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)


class TopographyView(QWidget):
    """Designer-owned controls with a programmatic plot and async calculation."""

    def __init__(self, parent=None, colour_step=1.2):
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
        self._colour_levels = (0., 1.)
        self._colour_step = float(colour_step)
        self._persistent_grid = None
        self._persistent_end = None
        self._persistent_key = None
        self._load_designer_controls()
        self._bind_controls()
        self._build_plot()
        self._connect_controls()
        set_panel_expanded(self.expand, False)
        self.settings_changed()

    def _load_designer_controls(self):
        if not TOPOGRAPHY_UI_PATH.is_file():
            raise FileNotFoundError(f'Topography Designer layout not found: {TOPOGRAPHY_UI_PATH}')
        loader = QUiLoader()
        loader.setWorkingDirectory(QDir(str(DESIGNER_DIRECTORY)))
        self.designer_ui = loader.load(str(TOPOGRAPHY_UI_PATH), self)
        if self.designer_ui is None:
            raise RuntimeError(f'Qt Designer could not load {TOPOGRAPHY_UI_PATH}')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.designer_ui)

    def _control(self, name, widget_type):
        widget = self.designer_ui.findChild(widget_type, name)
        if widget is None:
            raise RuntimeError(f'TopographyView.ui is missing {widget_type.__name__} "{name}"')
        return widget

    def _bind_controls(self):
        self.band = self._control('topographyBand', QComboBox)
        self.source = self._control('topographySource', QComboBox)
        self.source.setItemData(0, 'processed')
        self.source.setItemData(1, 'raw')
        self.move = self._control('topographyMove', QToolButton)
        self.expand = self._control('topographyExpand', QToolButton)
        self.colour_minus = self._control('topographyColourMinus', QToolButton)
        self.colour_fit = self._control('topographyColourFit', QToolButton)
        self.colour_plus = self._control('topographyColourPlus', QToolButton)
        self.colour_auto = self._control('topographyColourAuto', QCheckBox)
        self.iaf = self._control('topographyUseIaf', QCheckBox)
        self.iaf_status = self._control('topographyIafStatus', QLabel)
        self.persistence_label = self._control('topographyPersistenceLabel', QLabel)
        self.persistence = self._control('topographyPersistence', QDoubleSpinBox)
        self.extrapolate = self._control('topographyExtrapolate', QCheckBox)
        self.status = self._control('topographyStatus', QLabel)
        self.plot_host = self._control('topographyPlotHost', QWidget)
        self.colorbar_host = self._control('topographyColorbarHost', QWidget)

    def _build_plot(self):
        self.plot = pg.PlotWidget(background='w')
        self.plot.hideAxis('left')
        self.plot.hideAxis('bottom')
        self.plot.setAspectLocked(True)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)
        self.plot.setXRange(-1.12, 1.12, padding=0)
        self.plot.setYRange(-1.05, 1.18, padding=0)
        self.image = SmoothTopographyImage(axisOrder='row-major')
        self._palette = list(TOPOGRAPHY_PALETTE)
        self._color_map = pg.ColorMap(np.linspace(0., 1., len(self._palette)),
                                      [pg.mkColor(color) for color in self._palette])
        self.image.setColorMap(self._color_map)
        self.plot.addItem(self.image)
        self._add_head_outline()
        self._add_sensor_markers()
        self.colorbar = TopographyColorScale()
        self.colorbar.setColors(self._palette)
        self.plot_host.layout().addWidget(self.plot)
        self.colorbar_host.layout().addWidget(
            self.colorbar, 0, Qt.AlignmentFlag.AlignVCenter)

    def _add_head_outline(self):
        a = np.linspace(0, 2*np.pi, 150)
        self.plot.plot(np.cos(a), np.sin(a), pen=pg.mkPen('#45445e', width=1.5))
        self.plot.plot([-.12, 0., .12], [.99, 1.15, .99], pen=pg.mkPen('#45445e', width=1.5))
        for side in (-1, 1):
            self.plot.plot(side*np.array([1., 1.08, 1.08, 1.]), [.18, .12, -.12, -.18],
                           pen=pg.mkPen('#45445e', width=1.5))

    def _add_sensor_markers(self):
        self.sensors = pg.ScatterPlotItem(
            size=6, symbol='o', pen=pg.mkPen('#262735', width=1.),
            brush=(255, 255, 255, 170), hoverable=True,
            tip=lambda x, y, data: str(data))
        self.sensors.setZValue(1.)
        self.plot.addItem(self.sensors)

    def _connect_controls(self):
        for widget in (self.band, self.source):
            widget.currentIndexChanged.connect(self.settings_changed)
        self.persistence.valueChanged.connect(self.settings_changed)
        self.iaf.toggled.connect(self.settings_changed)
        self.extrapolate.toggled.connect(self.settings_changed)
        self.colour_minus.clicked.connect(lambda: self.adjust_colours(self._colour_step))
        self.colour_plus.clicked.connect(lambda: self.adjust_colours(1/self._colour_step))
        self.colour_fit.clicked.connect(self.fit_colours)
        self.colour_auto.toggled.connect(self.set_colour_auto)

    def settings(self):
        return TopographySettings(self.band.currentText(), self.source.currentData(),
                                  ANALYSIS_WINDOW_SECONDS, ANALYSIS_OVERLAP,
                                  self.persistence.value(), self.iaf.isChecked(),
                                  self.extrapolate.isChecked())

    def settings_changed(self, *_):
        unfiltered = self.band.currentText() == 'Unfiltered'
        self.persistence.setEnabled(True)
        self.persistence_label.setEnabled(True)
        self.source.setEnabled(not unfiltered)
        if unfiltered:
            self.iaf.setEnabled(False)
        self.reset()

    def reset(self):
        self._revision += 1
        self._key = None
        self._last_end = None
        self._next_tick = 0.
        self._persistent_grid = None
        self._persistent_end = None
        self._persistent_key = None
        self.clear('Waiting for EEG samples')

    def clear(self, message):
        self.result = None
        self.image.clear()
        self.sensors.clear()
        self._sensor_key = None
        self.status.setText(message)
        self.status.setToolTip(message)
        self.status.show()
        for button in (self.colour_minus, self.colour_fit, self.colour_plus):
            button.setEnabled(False)
        self.colour_auto.setEnabled(False)

    def _apply_colour_levels(self):
        self.colorbar.setLevels(self._colour_levels)
        self.image.setLevels(self._colour_levels)

    def _display_grid(self, result, config):
        """Apply visual persistence to band maps; voltage already uses τ in its estimator."""
        current = np.asarray(result['grid'], dtype=float)
        sensor_key = (result['band'], config.source,
                      tuple(result['labels']), tuple(result['positions']))
        tau = float(config.persistence)
        if (result['band'] != 'Unfiltered' and tau > 0.
                and self._persistent_grid is not None
                and self._persistent_key == sensor_key
                and self._persistent_end is not None):
            dt = float(result['end']) - self._persistent_end
            if dt > 0.:
                alpha = 1. - np.exp(-dt / tau)
                previous = self._persistent_grid
                valid = np.isfinite(current) & np.isfinite(previous)
                current = current.copy()
                current[valid] = previous[valid] + alpha * (current[valid] - previous[valid])
                finite = np.isfinite(current)
                low = float(np.min(current[finite]))
                high = float(np.max(current[finite]))
                if high > low:
                    current[finite] = (current[finite] - low) / (high - low)
                else:
                    current[finite] = .5
        self._persistent_grid = current.copy()
        self._persistent_end = float(result['end'])
        self._persistent_key = sensor_key
        return current

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
        if self.result is None:
            return
        self.colour_auto.setChecked(False)
        high = float(np.clip(self._colour_levels[1]*factor, .05, 5.))
        self._colour_levels = (0., high)
        self._apply_colour_levels()

    def tick(self, state, iaf=None, iaf_bands=None):
        if self._closing or not self.isVisible():
            return
        config = self.settings()
        valid_iaf = (iaf is not None and np.isfinite(iaf) and 6. <= iaf <= 16.)
        self.iaf.setEnabled(not (self.band.currentText() == 'Unfiltered') and valid_iaf)
        use_individual = (valid_iaf and self.iaf.isChecked()
                          and self.band.currentText() != 'Unfiltered')
        self.iaf_status.setText(f'{iaf:.1f} Hz' if valid_iaf else 'No IAF')
        self.iaf_status.setToolTip(
            (f'Calibrated IAF: {iaf:.2f} Hz. '
             + ('Using the saved IAF-derived band boundaries.' if use_individual
                else 'Using the fixed canonical band boundaries.'))
            if valid_iaf else 'No calibrated IAF loaded; canonical fixed bands are used.')
        history = state.visible_history('EEG')
        if not history or state.origin is None:
            if self._key is not None:
                self.reset()
            return
        end = min(state.viewport('EEG')[1] + state.origin, float(history[-1][0][-1]))
        scales = np.asarray(state.display_scales.get('EEG', DEFAULT_EEG_DISPLAY_STEP))
        factors = DEFAULT_EEG_DISPLAY_STEP / scales
        band_key = tuple((name, tuple(values)) for name, values in sorted((iaf_bands or {}).items()))
        key = (state.signals.generations['EEG'], config, iaf, band_key,
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
                                         factors, state.units['EEG'], iaf, iaf_bands)

    def present(self, result, config, _origin, _paused):
        self.result = result
        if self.colour_auto.isChecked() or self._colour_levels is None:
            self._colour_levels = tuple(result['levels'])
        for button in (self.colour_minus, self.colour_fit, self.colour_plus):
            button.setEnabled(True)
        self.colour_auto.setEnabled(True)
        display_grid = self._display_grid(result, config)
        self.image.setImage(display_grid, autoLevels=False, levels=self._colour_levels)
        # ImageItem.setRect() derives its transform from the assigned image size.
        # It must run after setImage(), otherwise the map is scaled as a 1x1 image.
        self.image.setRect(QRectF(-1., -1., 2., 2.))
        self.colorbar.setLevels(self._colour_levels)
        sensor_key = (tuple(result['labels']), tuple(result['positions']))
        if sensor_key != self._sensor_key:
            xy = np.asarray(result['positions'])
            self.sensors.setData(xy[:, 0], xy[:, 1], data=result['labels'])
            self._sensor_key = sensor_key
        self.status.clear()
        self.status.hide()

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
