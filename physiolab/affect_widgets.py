"""Affect presentation: persistent geometry and controls, without processing state.

The host supplies immutable affect snapshots and original (un-normalized) EI
observations. Missing responses never acquire a placeholder marker at zero.
"""
import math
from pathlib import Path
from PySide6.QtUiTools import QUiLoader
from .flow_layout import install_flow
from .panel_arrangement import PanelArrangement
from .ui_icons import set_action, set_panel_expanded, set_view_paused

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, QDir, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget, QSplitter, QToolButton,
)

from .affect_state import AffectSnapshot, RESPONSE_DEFINITIONS

INK = '#25234a'
MUTED = '#77768f'
RULE = '#e7e5f1'
NEGATIVE = '#a65d8d'
POSITIVE = '#138d90'
RETENTIONS = (5, 15, 30, 60, 120)
EI_MAX_GAP_SECONDS = 2.
NORMALIZATIONS = (
    ('Baseline z-score', 'zscore'), ('Robust MAD', 'zmad'),
    ('Robust IQR', 'robust_iqr'), ('Baseline min–max', 'minmax'),
)


def _color(value, alpha=1.):
    color = QColor(value)
    color.setAlphaF(max(0., min(1., alpha)))
    return color


def trajectory_geometry(response, now, retention, fade):
    """Disjoint segment vertices/alpha; never bridge invalid or stale pairs."""
    points = response.points
    vertices, colors = [], []
    rgb = QColor(response.color).getRgbF()[:3]
    for previous, current in zip(points, points[1:]):
        if not current.connected:
            continue
        if not all(math.isfinite(v) for p in (previous, current) for v in (p.x, p.y)):
            continue
        for point in (previous, current):
            alpha = max(.08, 1. - max(0., now-point.at)/retention) if fade else .8
            vertices.append((point.x, point.y))
            colors.append((*rgb, alpha))
    return (np.asarray(vertices, dtype=np.float32).reshape(-1, 2),
            np.asarray(colors, dtype=np.float32).reshape(-1, 4))


class AffectPlane(QWidget):
    """One stable VisPy scene. Offscreen Qt uses an equivalent painter surface."""

    range_changed = Signal()
    auto_range_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.responses = ()
        self.now, self.retention, self.fade = 0., 60., True
        self.extent = 2.
        self.auto_range = True
        self._setting_range = False
        self._last_camera_rect = None
        self.canvas = None
        self.layers = {}
        self._fallback = QApplication.platformName() in ('offscreen', 'minimal')
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def showEvent(self, event):
        super().showEvent(event)
        if self.canvas is None and not self._fallback:
            self._initialize_scene()
            self._apply_range()
            self._render_scene()

    def _initialize_scene(self):
        from vispy import scene
        self.canvas = scene.SceneCanvas(keys=None, show=False, bgcolor='white', app='pyside6', parent=self)
        self._layout.addWidget(self.canvas.native)
        self.view = self.canvas.central_widget.add_view()
        self.view.camera = scene.PanZoomCamera(aspect=1)
        self.view.camera.transform.changed.connect(self._camera_changed)
        self.reference = scene.visuals.Line(color='#d8d4e8', width=1.,
                                           parent=self.view.scene, connect='segments')
        self.circle = scene.visuals.Line(color='#e7e4f1', width=1., parent=self.view.scene)
        theta = np.linspace(0., 2.*np.pi, 180)
        self.circle.set_data(pos=np.column_stack((np.cos(theta), np.sin(theta))).astype(np.float32))
        # Allocated once: ticking, pausing and expanding only update buffers.
        for key, _, color, *_ in RESPONSE_DEFINITIONS:
            line = scene.visuals.Line(parent=self.view.scene, connect='segments', width=2.5)
            marker = scene.visuals.Markers(parent=self.view.scene)
            self.layers[key] = (line, marker)

    def set_snapshot(self, snapshot, now, retention, fade):
        self.responses = snapshot.responses
        self.now, self.retention, self.fade = float(now), float(retention), bool(fade)
        if self.auto_range:
            target = self._fit_extent()
            if target != self.extent:
                self.extent = target
                self._apply_range()
        if self.canvas is not None:
            self._render_scene()
        self.update()

    def _fit_extent(self):
        largest = max((abs(v) for response in self.responses for point in response.points
                       for v in (point.x, point.y) if math.isfinite(v)), default=1.)
        return max(2., largest * 1.18)

    def set_auto_range(self, enabled):
        self.auto_range = bool(enabled)
        self.auto_range_changed.emit(self.auto_range)
        if self.auto_range:
            self.fit()

    def fit(self):
        """Fit all retained observations without changing the selected range mode."""
        self.extent = self._fit_extent()
        self._apply_range()

    def zoom(self, factor):
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError('Zoom factor must be finite and positive')
        self.set_auto_range(False)
        self.extent *= factor
        if self.canvas is not None:
            self.view.camera.zoom(factor)
        else:
            self.range_changed.emit()
            self.update()

    def _apply_range(self):
        if self.canvas is not None:
            self._setting_range = True
            try:
                extent = self.extent
                self.view.camera.set_range(x=(-extent, extent), y=(-extent, extent),
                                           z=(-1., 1.), margin=0.)
            finally:
                self._setting_range = False
        self.range_changed.emit()
        self.update()

    def _camera_changed(self, event=None):
        rect = self.view.camera.rect
        signature = (rect.left, rect.bottom, rect.width, rect.height)
        if (not self._setting_range and self._last_camera_rect is not None
                and signature != self._last_camera_rect and self.auto_range):
            # Mouse pan/zoom selects manual range. Resizing keeps the same
            # camera rectangle and does not accidentally disable auto mode.
            self.auto_range = False
            self.auto_range_changed.emit(False)
        self._last_camera_rect = signature
        self.extent = max(abs(rect.width), abs(rect.height))/2.
        if hasattr(self, 'reference'):
            self._update_reference()
        self.range_changed.emit()

    @property
    def display_bounds(self):
        """Actual visible ranges, including aspect preservation and user pan."""
        if self.canvas is None:
            return (-self.extent, self.extent, -self.extent, self.extent)
        camera = self.view.camera
        width, height = self.view.size
        corners = camera.transform.imap(np.asarray([[0., 0., 0.], [width, height, 0.]]))
        return (min(corners[:, 0]), max(corners[:, 0]),
                min(corners[:, 1]), max(corners[:, 1]))

    def _update_reference(self):
        left, right, bottom, top = self.display_bounds
        self.reference.set_data(pos=np.asarray([[left, 0], [right, 0],
                                                [0, bottom], [0, top]], dtype=np.float32))

    def _render_scene(self):
        self._update_reference()
        for line, marker in self.layers.values():
            line.visible = marker.visible = False
        for response in self.responses:
            line, marker = self.layers[response.key]
            positions, colors = trajectory_geometry(response, self.now, self.retention, self.fade)
            if len(positions):
                line.set_data(pos=positions, color=colors, connect='segments')
                line.visible = True
            if response.current is not None:
                point = response.current
                marker.set_data(pos=np.asarray([[point.x, point.y]], dtype=np.float32),
                                face_color=response.color, edge_color='white', edge_width=2., size=14.)
                marker.visible = True
        self.canvas.update()

    def _point(self, x, y):
        side = min(self.width(), self.height()) * .92
        return QPointF(self.width()/2 + x*side/(2*self.extent),
                       self.height()/2 - y*side/(2*self.extent))

    def paintEvent(self, event):
        if not self._fallback:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        painter.setPen(QPen(QColor(RULE), 1))
        for begin, end in (((-self.extent, 0), (self.extent, 0)),
                           ((0, -self.extent), (0, self.extent))):
            painter.drawLine(self._point(*begin), self._point(*end))
        center = self._point(0, 0)
        radius = self._point(1, 0).x()-center.x()
        painter.drawEllipse(center, radius, radius)
        for response in self.responses:
            positions, colors = trajectory_geometry(response, self.now, self.retention, self.fade)
            for index in range(0, len(positions), 2):
                painter.setPen(QPen(_color(response.color, float(colors[index+1, 3])), 2.5))
                painter.drawLine(self._point(*positions[index]), self._point(*positions[index+1]))
            if response.current is not None:
                point = response.current
                painter.setPen(QPen(Qt.GlobalColor.white, 2))
                painter.setBrush(QColor(response.color))
                painter.drawEllipse(self._point(point.x, point.y), 7., 7.)

    def closeEvent(self, event):
        if self.canvas is not None:
            canvas = self.canvas
            self.view.camera.transform.changed.disconnect(self._camera_changed)
            # An embedded SceneCanvas.close() hides its QOpenGLWidget but does
            # not destroy it. Release that native context while Qt is alive,
            # rather than leaving a hidden GL child until interpreter teardown.
            native = canvas.native
            canvas.close()
            self._layout.removeWidget(native)
            native.deleteLater()
            QCoreApplication.sendPostedEvents(native, QEvent.Type.DeferredDelete)
            self.canvas = None
        super().closeEvent(event)


class EmotionalIndexPlot(QWidget):
    """Original signed EI gauge and history, drawn with Qt's native renderer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self.points = ()
        self.now, self.retention = 0., 60.
        self.current = None

    def set_points(self, points, now, retention):
        self.now, self.retention = float(now), float(retention)
        observations = tuple((float(t), float(v)) for t, v in points
                             if math.isfinite(t) and t <= now)
        self.points = tuple(p for p in observations if p[0] >= now-retention)
        self.current = (observations[-1][1] if observations
                        and math.isfinite(observations[-1][1]) else None)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        left, right = 24., width-24.
        middle = width/2.
        color = POSITIVE if self.current is not None and self.current >= 0 else NEGATIVE
        painter.setPen(QColor(color if self.current is not None else MUTED))
        font = QFont(self.font())
        font.setPointSize(34)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(QRectF(0, 4, width, 64), Qt.AlignmentFlag.AlignCenter,
                         '—' if self.current is None else f'{self.current:+.2f}')
        font.setPointSize(9)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(0, 67, width, 24), Qt.AlignmentFlag.AlignCenter,
                         'ORIGINAL EMOTIONAL INDEX')
        gauge_y = 115.
        gradient = QLinearGradient(left, 0, right, 0)
        gradient.setColorAt(0., _color(NEGATIVE, .65))
        gradient.setColorAt(.5, QColor('#eeedf5'))
        gradient.setColorAt(1., _color(POSITIVE, .65))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(QRectF(left, gauge_y, right-left, 11.), 5., 5.)
        painter.setPen(QPen(QColor('#b8b3ce'), 1.))
        painter.drawLine(QPointF(middle, gauge_y-7), QPointF(middle, gauge_y+18))
        if self.current is not None:
            x = middle + self.current*(right-left)/2.
            painter.setPen(QPen(Qt.GlobalColor.white, 3.))
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(x, gauge_y+5.5), 8., 8.)
        painter.setPen(QColor(NEGATIVE))
        painter.drawText(QRectF(left, gauge_y+24, 95, 22), Qt.AlignmentFlag.AlignLeft, '−1 · Negative')
        painter.setPen(QColor(POSITIVE))
        painter.drawText(QRectF(right-95, gauge_y+24, 95, 22), Qt.AlignmentFlag.AlignRight, 'Positive · +1')
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(middle-20, gauge_y+24, 40, 22), Qt.AlignmentFlag.AlignCenter, '0')
        top = 190.
        bottom = max(top+40., height-28.)
        center_y = (top+bottom)/2.
        painter.setPen(QPen(QColor(RULE), 1.))
        painter.drawLine(QPointF(left, center_y), QPointF(right, center_y))
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(left, top-25, right-left, 20), 'RECENT HISTORY')
        for first, second in zip(self.points, self.points[1:]):
            if (not all(math.isfinite(v) for _, v in (first, second))
                    or second[0]-first[0] > EI_MAX_GAP_SECONDS):
                continue
            # Break at zero so the signed line remains accurate in both colors.
            pairs = [first, second]
            if first[1]*second[1] < 0:
                fraction = -first[1]/(second[1]-first[1])
                pairs.insert(1, (first[0]+fraction*(second[0]-first[0]), 0.))
            for begin, end in zip(pairs, pairs[1:]):
                painter.setPen(QPen(QColor(POSITIVE if begin[1]+end[1] >= 0 else NEGATIVE), 2.))
                def position(point):
                    return QPointF(right-(self.now-point[0])*(right-left)/self.retention,
                                   center_y-point[1]*(bottom-top)/2.)
                painter.drawLine(position(begin), position(end))
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(left, bottom+5, 90, 20), f'−{self.retention:g} s')
        painter.drawText(QRectF(right-45, bottom+5, 45, 20), Qt.AlignmentFlag.AlignRight, 'now')


class AffectView(QWidget):
    """Two affect cards. Host owns histories, references and processing lifecycle."""

    normalization_changed = Signal(str)
    retention_changed = Signal(float)
    clear_requested = Signal()
    pause_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peripheral_available = True
        self._ei_reason = None
        self.setObjectName('affectView')
        self.setStyleSheet('''
            QFrame[affectCard="true"] { background: white; border: 1px solid #dfe1ef; border-radius: 9px; }
            QLabel[affectHeading="true"] { color: #25234a; font-size: 11pt; font-weight: 600; border: none; }
            QLabel[affectEyebrow="true"] { color: #77768f; font-size: 8pt; font-weight: 600; border: none; }
            QLabel#affectHint { color: #77768f; font-size: 9pt; border: none; }
            QLabel#affectReadout { border: none; font-size: 9pt; }
        ''')
        self._latest = None
        self._active = True
        self._focus = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 12, 10, 8)
        outer.setSpacing(12)
        folder = Path(__file__).resolve().parent.parent / 'designer'
        controls_loader = QUiLoader()
        controls_loader.setWorkingDirectory(QDir(str(folder)))
        self.controls = controls_loader.load(str(folder / 'AffectControls.ui'), self)
        if self.controls is None:
            raise RuntimeError('Cannot load Designer Affect controls')
        self.normalization = self.controls.findChild(QComboBox, 'affectNormalization')
        self.retention = self.controls.findChild(QComboBox, 'affectRetention')
        self.fade = self.controls.findChild(QCheckBox, 'affectFade')
        self.pause = self.controls.findChild(QPushButton, 'affectPause')
        self.clear = self.controls.findChild(QPushButton, 'affectClear')
        for label, value in NORMALIZATIONS:
            self.normalization.addItem(label, value)
        self.normalization.setToolTip('All four circumplex axes use this method with their own BSL reference.')
        for seconds in RETENTIONS:
            self.retention.addItem(f'{seconds} s', float(seconds))
        self.retention.setCurrentIndex(RETENTIONS.index(60))
        set_view_paused(self.pause, False)
        self.clear.setToolTip('Clear visible trails; acquisition and processing continue.')
        install_flow(self.controls)
        outer.addWidget(self.controls)
        loader = QUiLoader()
        loader.setWorkingDirectory(QDir(str(folder)))
        self.cards_splitter = loader.load(str(folder / 'AffectWorkspace.ui'), self)
        if self.cards_splitter is None:
            raise RuntimeError('Cannot load Designer Affect workspace')
        self.cards_splitter.setChildrenCollapsible(False)
        self.cards_splitter.setHandleWidth(9)
        self.cards_splitter.setStretchFactor(0, 3)
        self.cards_splitter.setStretchFactor(1, 2)
        self.cards_splitter.setSizes([700, 400])
        self.circumplex_card = self.cards_splitter.findChild(QFrame, 'circumplexCard')
        self.ei_card = self.cards_splitter.findChild(QFrame, 'eiCard')
        plane_layout, ei_layout = self.circumplex_card.layout(), self.ei_card.layout()
        outer.addWidget(self.cards_splitter, 1)
        self.arrangement = PanelArrangement(self, self.cards_splitter,
            {'circumplex':self.circumplex_card, 'ei':self.ei_card},
            {key:self.cards_splitter.findChild(QToolButton, key+'Move') for key in ('circumplex','ei')},
            {'circumplex':'Affect landscape', 'ei':'Emotional Index'})
        self.arrangement.changed.connect(self._arrangement_changed)
        for key in ('circumplex','ei'):
            self.cards_splitter.findChild(QPushButton,key+'Expand').clicked.connect(
                lambda checked=False,k=key:self._expand(k))
        self.top_axis = self._label('Higher arousal', 'affectHint', Qt.AlignmentFlag.AlignCenter)
        plane_layout.addWidget(self.top_axis)
        self.plane = AffectPlane()
        range_controls = QHBoxLayout()
        self.auto_range = QCheckBox('Auto range')
        self.auto_range.setChecked(True)
        self.auto_range.setToolTip('Keep every retained observation visible. Pan or zoom to select a manual range.')
        self.zoom_in = QPushButton()
        set_action(self.zoom_in, '', 'plus')
        self.zoom_out = QPushButton()
        set_action(self.zoom_out, '', 'minus')
        self.fit_range = QPushButton()
        set_action(self.fit_range, '', 'autoscale')
        self.fit_range.setAccessibleName('Fit visible range')
        self.zoom_in.setToolTip('Zoom in; keep this manual range as observations arrive.')
        self.zoom_out.setToolTip('Zoom out; keep this manual range as observations arrive.')
        self.fit_range.setToolTip('Fit all retained observations once.')
        range_controls.addWidget(self.auto_range)
        range_controls.addStretch()
        for button in (self.zoom_out, self.fit_range, self.zoom_in):
            button.setMaximumWidth(46)
            range_controls.addWidget(button)
        plane_layout.addLayout(range_controls)
        plane_layout.addWidget(self.plane, 1)
        self.bottom_axis = self._label('Lower arousal', 'affectHint', Qt.AlignmentFlag.AlignCenter)
        plane_layout.addWidget(self.bottom_axis)
        horizontal = QHBoxLayout()
        horizontal.addWidget(self._label('← Lower valence', 'affectHint'))
        horizontal.addStretch()
        horizontal.addWidget(self._label('Higher valence →', 'affectHint'))
        plane_layout.addLayout(horizontal)
        self.range_label = self._label('Normalized axes · reference circle = 1', 'affectHint', Qt.AlignmentFlag.AlignCenter)
        plane_layout.addWidget(self.range_label)
        self.readouts = {}
        self._bindings = {}
        for key, name, color, x, y in RESPONSE_DEFINITIONS:
            self._bindings[key] = f'{x[1]} × {y[1].replace("_TONIC", " tonic")}'
            label = self._label(f'●  {name}  ·  awaiting data', 'affectReadout')
            label.setStyleSheet(f'color: {color}; border: none;')
            label.setWordWrap(True)
            label.setToolTip(f'Valence: {x[1]} · Arousal: {y[1]}')
            self.readouts[key] = label
            plane_layout.addWidget(label)
        self.ei_plot = EmotionalIndexPlot()
        ei_layout.addWidget(self.ei_plot, 1)
        self.ei_status = self._label('Awaiting original EI observations', 'affectHint')
        self.ei_status.setWordWrap(True)
        ei_layout.addWidget(self.ei_status)
        note = self._label('Zero is the numerical reference. EI is separate from valence and arousal.', 'affectHint')
        note.setWordWrap(True)
        ei_layout.addWidget(note)
        self.normalization.currentIndexChanged.connect(lambda: self.normalization_changed.emit(self.normalization.currentData()))
        self.retention.currentIndexChanged.connect(self._retention_changed)
        self.fade.toggled.connect(lambda: self._refresh())
        self.pause.toggled.connect(self._pause_changed)
        self.clear.clicked.connect(self._clear)
        self.auto_range.toggled.connect(self.plane.set_auto_range)
        self.plane.auto_range_changed.connect(self._sync_auto_range)
        self.plane.range_changed.connect(self._update_range_label)
        self.zoom_in.clicked.connect(lambda: self.plane.zoom(.8))
        self.zoom_out.clicked.connect(lambda: self.plane.zoom(1.25))
        self.fit_range.clicked.connect(self.plane.fit)

    @staticmethod
    def _label(text, name, alignment=None):
        label = QLabel(text)
        label.setObjectName(name)
        if alignment is not None:
            label.setAlignment(alignment)
        return label

    def _arrangement_changed(self, order):
        self._focus = None
        self._sync_card_visibility()

    def _expand(self, key):
        if key == 'ei' and not self._peripheral_available:
            return
        self._focus = None if self._focus == key else key
        self._sync_card_visibility()

    def _sync_card_visibility(self):
        self.circumplex_card.setVisible(self._focus in (None, 'circumplex'))
        self.ei_card.setVisible(self._peripheral_available and self._focus in (None, 'ei'))
        for key in ('circumplex','ei'):
            self.cards_splitter.findChild(QToolButton,key+'Move').setEnabled(self._peripheral_available)
        for button in self.findChildren(QPushButton):
            card_key = button.property('affectCardKey')
            if card_key:
                set_panel_expanded(button, self._focus == card_key)

    def _retention_changed(self):
        self.retention_changed.emit(float(self.retention.currentData()))
        self._refresh()

    def _pause_changed(self, paused):
        set_view_paused(self.pause, paused)
        self.pause_changed.emit(paused)
        if not paused:
            self._refresh()

    def set_active(self, active):
        self._active = bool(active)
        if active:
            self._refresh()

    def update_snapshot(self, snapshot, ei_points, now, ei_status=None):
        self._ei_reason = ei_status
        if not self._peripheral_available:
            snapshot = AffectSnapshot(tuple(r for r in snapshot.responses if r.key != 'peripheral'))
            ei_points = ()
        self._latest = (snapshot, tuple(ei_points), float(now))
        self._refresh()

    def set_peripheral_available(self, available):
        available = bool(available)
        if available == self._peripheral_available:
            return
        self._peripheral_available = available
        if not available and self._focus == 'ei':
            self._focus = None
        self._sync_card_visibility()
        self.readouts['peripheral'].setVisible(available)
        if not available:
            # Source removal clears unavailable geometry even in a paused view.
            snapshot = AffectSnapshot(tuple(r for r in self.plane.responses if r.key != 'peripheral'))
            self.plane.set_snapshot(snapshot, self.plane.now,
                                    float(self.retention.currentData()), self.fade.isChecked())
            self.ei_plot.set_points((), self.plane.now, float(self.retention.currentData()))
            if self._latest is not None:
                self._latest = (snapshot, (), self._latest[2])

    def _sync_auto_range(self, checked):
        self.auto_range.blockSignals(True)
        self.auto_range.setChecked(checked)
        self.auto_range.blockSignals(False)

    def _update_range_label(self):
        units = {'zscore': 'σ', 'zmad': 'σ (MAD)', 'robust_iqr': 'σ (IQR)', 'minmax': 'norm.'}
        unit = units[self.normalization.currentData()]
        left, right, bottom, top = self.plane.display_bounds
        self.range_label.setText(f'V {left:+.1f}…{right:+.1f} · A {bottom:+.1f}…{top:+.1f} {unit} · circle = 1')

    def clear_display(self):
        """Clear visible/frozen geometry immediately, preserving pause and controls."""
        self._latest = None
        now = self.plane.now
        self.plane.set_snapshot(AffectSnapshot(()), now,
                                float(self.retention.currentData()), self.fade.isChecked())
        self.ei_plot.set_points((), now, float(self.retention.currentData()))
        for key, name, *_ in RESPONSE_DEFINITIONS:
            self.readouts[key].setText(f'●  {name}  ·  awaiting data')
            self.readouts[key].setToolTip('Awaiting fresh observations')
        self.ei_status.setText('Awaiting fresh original EI observations')
        self._update_range_label()

    def _clear(self):
        self.clear_display()
        self.clear_requested.emit()

    def _refresh(self):
        if self._latest is None or self.pause.isChecked() or not self._active:
            return
        snapshot, ei_points, now = self._latest
        retention = float(self.retention.currentData())
        self.plane.set_snapshot(snapshot, now, retention, self.fade.isChecked())
        self.ei_plot.set_points(ei_points, now, retention)
        self._update_range_label()
        for response in snapshot.responses:
            point = response.current
            value = (f'V {point.x:+.2f} · A {point.y:+.2f} · {max(0., now-point.at):.1f} s old'
                     if point is not None else response.status)
            binding = self._bindings[response.key]
            self.readouts[response.key].setText(f'●  {response.name} ({binding})  ·  {value}')
            if point is not None:
                self.readouts[response.key].setToolTip(
                    f'{binding} · normalized with separate fixed baseline references\n'
                    f'Source timestamps: {point.source_times[0]:.3f}, {point.source_times[1]:.3f}\n'
                    f'Observation age: {max(0., now-point.at):.2f} s\n{response.status}')
        self.ei_status.setText('Live · original signed EI' if self.ei_plot.current is not None
                               else self._ei_reason or 'Awaiting fresh original EI observations')

    def closeEvent(self, event):
        self.plane.close()
        super().closeEvent(event)
