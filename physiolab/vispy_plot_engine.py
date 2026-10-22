"""Shared clean VisPy scene, axes policy, and blue sweep cursor.

The same presentation engine hosts both Raw Data and Metrics.
"""
import math
import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget, QSizePolicy, QGridLayout

from .render_policy import RAW_DISPLAY_POLICY
from .scale_rulers import ScaleRuler


class _ChannelLabelGutter(QWidget):
    """Paint channel labels at trace baselines without imposing a plot height."""

    LABEL_GAP = 3

    def __init__(self):
        super().__init__()
        self.names = ()
        self.visible_indices = ()
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Ignored)
        self.setStyleSheet('color: #718096; font-size: 9pt; border: none;')

    def set_names(self, names):
        self.names = tuple(names)
        self.setToolTip('Channels (bottom to top):\n' + '\n'.join(self.names))
        self.update_density()

    def update_density(self):
        count = len(self.names)
        if not count or self.height() < self.fontMetrics().height():
            self.visible_indices = ()
        else:
            spacing = RAW_DISPLAY_POLICY.channel_spacing * self.height() / RAW_DISPLAY_POLICY.span(count)
            stride = max(1, math.ceil((self.fontMetrics().height() + self.LABEL_GAP) / spacing))
            indices = list(range(0, count, stride))
            # Include the uppermost channel when its label fits independently.
            if count > 1 and indices[-1] != count - 1:
                if len(indices) > 1 and count - 1 - indices[-1] < stride:
                    indices.pop()
                if (count - 1 - indices[-1]) * spacing >= self.fontMetrics().height() + self.LABEL_GAP:
                    indices.append(count - 1)
            half_height = self.fontMetrics().height() / 2.
            self.visible_indices = tuple(index for index in indices
                                         if half_height <= self.label_center(index)
                                         <= self.height() - half_height)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_density()

    def label_center(self, index):
        return self.height() * (1. - RAW_DISPLAY_POLICY.label_fraction(index, len(self.names)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        height = self.fontMetrics().height()
        for index in self.visible_indices:
            rect = QRectF(0, self.label_center(index) - height / 2., self.width() - 6, height)
            text = self.fontMetrics().elidedText(self.names[index], Qt.TextElideMode.ElideRight, self.width() - 6)
            painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)



class VisPyPlotEngine:
    """White, borderless, full-canvas OpenGL plot with an optional sweep cursor."""

    def __init__(self, x_label='Time (s)', y_label='Value', size=(900, 350),
                 show_axes=False):
        from vispy import scene
        self.scene = scene
        self.canvas = scene.SceneCanvas(
            keys=None, show=False, bgcolor='white', size=size, app='pyside6'
        )
        self.widget = QWidget()
        layout = QGridLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.label_gutter = _ChannelLabelGutter()
        self.label_gutter.setFixedWidth(48)
        self.time_footer = ScaleRuler(Qt.Orientation.Horizontal)
        self.amplitude_ruler = ScaleRuler(Qt.Orientation.Vertical)
        self.amplitude_ruler.hide()
        self._amplitude_range = None
        layout.addWidget(self.label_gutter, 0, 0)
        layout.addWidget(self.canvas.native, 0, 1)
        layout.addWidget(self.time_footer, 1, 1)
        layout.addWidget(self.amplitude_ruler, 0, 2)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(0, 1)
        self.label_gutter.hide()
        self.xaxis = self.yaxis = None
        if show_axes:
            grid = self.canvas.central_widget.add_grid(margin=4, spacing=3)
            self.yaxis = scene.AxisWidget(
                orientation='left', axis_label=y_label,
                text_color='#303030', axis_color='#888888',
                tick_color='#888888')
            self.xaxis = scene.AxisWidget(
                orientation='bottom', axis_label=x_label,
                text_color='#303030', axis_color='#888888',
                tick_color='#888888')
            grid.add_widget(self.yaxis, row=0, col=0)
            grid.add_widget(self.xaxis, row=1, col=1)
            self.view = grid.add_view(row=0, col=1)
            self.yaxis.width_max = 74
            self.xaxis.height_max = 55
        else:
            self.view = self.canvas.central_widget.add_view()
        self.view.camera = scene.PanZoomCamera(rect=(0, 0, 1, 1), aspect=None)
        self.view.camera.interactive = False
        if show_axes:
            self.xaxis.link_view(self.view)
            self.yaxis.link_view(self.view)
        self.sweep_cursor = self.line('#1769e0', width=2)
        self.sweep_cursor.order = 1000  # Keep the shared playhead above dense EEG traces.
        self.sweep_cursor.visible = False
        self._y_bounds = (0., 1.)
        self._view_rect = None
        self._channel_names = None
        self._axis_duration = 5.
        self._update_rulers()
        self.canvas.events.resize.connect(self._update_rulers)

    def _update_rulers(self, event=None):
        width = max(1, self.canvas.native.width())
        height = max(1, self.canvas.native.height())
        self.time_footer.set_scale((self._axis_duration or 5.) / width, 's')
        if self._amplitude_range is not None:
            span, unit = self._amplitude_range
            self.amplitude_ruler.set_scale(span / height, unit)

    def set_amplitude_range(self, span, unit):
        self._amplitude_range = (float(span), unit)
        self.amplitude_ruler.show()
        self._update_rulers()

    def line(self, color='black', width=1):
        return self.scene.visuals.Line(
            parent=self.view.scene, color=color, method='gl',
            connect='segments', width=width, antialias=False)

    def markers(self):
        return self.scene.visuals.Markers(parent=self.view.scene)

    def set_view(self, left, right, bottom, top):
        if right <= left or top <= bottom:
            return
        rect = (float(left), float(bottom),
                float(right-left), float(top-bottom))
        if rect == self._view_rect:
            return
        self._view_rect = rect
        self._y_bounds = (float(bottom), float(top))
        # Never introspect the bounds of empty VisPy Markers.
        self.view.camera.rect = rect
        self.canvas.update()

    @property
    def channel_names(self):
        """Source channel names painted by the Qt gutter, bottom to top."""
        return self._channel_names or ()

    @property
    def time_duration(self):
        """Physical sweep duration represented by the time ruler."""
        return self._axis_duration

    @property
    def y_bounds(self):
        """Current vertical extent of the scene camera."""
        return self._y_bounds

    def set_axis_labels(self, duration=None, bounds=None):
        """Update physical scale metadata without allocating scene annotations."""
        if duration is not None and np.isfinite(duration) and duration > 0:
            self._axis_duration = float(duration)
            self._update_rulers()
        if bounds is not None:
            bottom, top = map(float, bounds)
            if np.isfinite((bottom, top)).all() and top > bottom:
                left, _, width, _ = self._view_rect or (0., 0., 1., 1.)
                self.set_view(left, left + width, bottom, top)
        self.canvas.update()

    def set_channel_labels(self, names):
        """Update the painted Qt gutter without allocating child label widgets."""
        names = tuple(str(name) for name in names)
        if names == self._channel_names:
            return
        self._channel_names = names
        self.label_gutter.setVisible(bool(names))
        self.label_gutter.set_names(names)

    def set_sweep_cursor(self, phase):
        """Thin blue line; no white erase band is drawn."""
        phase = float(phase)
        if not np.isfinite(phase):
            self.sweep_cursor.visible = False
            return
        low, high = self._y_bounds
        x = min(1., max(0., phase))
        pos = np.array([[x, low], [x, high]], dtype=np.float32)
        self.sweep_cursor.set_data(pos=pos, color='#1769e0',
                                   connect='segments')
        self.sweep_cursor.visible = True
        self.canvas.update()

    def close(self):
        self.canvas.close()
