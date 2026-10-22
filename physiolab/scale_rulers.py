"""Small, independent physical scale bars for signal canvases.

The canvas supplies physical units per screen pixel after its view transform.
These widgets draw with Qt alone and never trigger acquisition or canvas work.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget
from .display_units import ARBITRARY_UNIT


@dataclass(frozen=True)
class ScaleBar:
    value: float
    pixels: float
    label: str


def scale_bar(units_per_pixel: float, unit: str, available_pixels: float,
              target_pixels: float = 80.0) -> ScaleBar | None:
    """Choose the largest 1/2/5 step within the desired screen length.

    The returned pixel length always corresponds exactly to ``value``;
    rounding the number shown never changes the geometry.
    """
    if (not math.isfinite(units_per_pixel) or units_per_pixel <= 0
            or not math.isfinite(available_pixels) or available_pixels < 1
            or not math.isfinite(target_pixels) or target_pixels <= 0):
        return None
    desired = units_per_pixel * min(available_pixels, target_pixels)
    if desired <= 0 or not math.isfinite(desired):
        return None
    exponent = math.floor(math.log10(desired))
    decade = 10.0 ** exponent
    if decade == 0:
        return None
    fraction = desired / decade
    step = 5 if fraction >= 5 else 2 if fraction >= 2 else 1
    value = step * decade
    return ScaleBar(value, value / units_per_pixel,
                    f'{value:g} {str(unit or "").strip() or ARBITRARY_UNIT}')


class ScaleRuler(QWidget):
    """A resize-aware scale bracket outside a plot's OpenGL surface.

    ``orientation`` accepts Qt.Horizontal or Qt.Vertical. ``set_scale`` takes
    positive physical units per pixel (seconds/pixel, microvolts/pixel, etc.).
    Invalid or unavailable scales hide the bracket until the view is ready.
    """

    EDGE_MARGIN = 8
    TICK_LENGTH = 5
    TARGET_PIXELS = 80.0

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(parent)
        self.orientation = Qt.Orientation(orientation)
        self._units_per_pixel = math.nan
        self._unit = ''
        self._bar = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if self.orientation == Qt.Orientation.Horizontal:
            self.setFixedHeight(32)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setFixedWidth(90)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def sizeHint(self):
        return QSize(120, 32) if self.orientation == Qt.Orientation.Horizontal else QSize(90, 120)

    @property
    def bar(self) -> ScaleBar | None:
        """Current physical value and exact bracket length, for inspection."""
        return self._bar

    def set_scale(self, units_per_pixel: float, unit: str):
        units_per_pixel = float(units_per_pixel)
        unit = str(unit or '').strip() or ARBITRARY_UNIT
        if units_per_pixel == self._units_per_pixel and unit == self._unit:
            return
        self._units_per_pixel, self._unit = units_per_pixel, unit
        self.setToolTip(f'Physical scale ({unit})' if unit else 'Physical scale')
        self._update_geometry()

    def _update_geometry(self):
        extent = self.width() if self.orientation == Qt.Orientation.Horizontal else self.height()
        self._bar = scale_bar(self._units_per_pixel, self._unit,
                              extent - 2 * self.EDGE_MARGIN, self.TARGET_PIXELS)
        if self.orientation == Qt.Orientation.Vertical and self._bar is not None:
            # Right-aligned text used to clip the leading number when the
            # unit or scientific notation exceeded the fixed label gutter.
            label_width = self.fontMetrics().horizontalAdvance(self._bar.label)
            width = max(self.sizeHint().width(), math.ceil(label_width) + 24)
            if self.width() != width:
                self.setFixedWidth(width)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_geometry()

    def paintEvent(self, event):
        if self._bar is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().color(self.foregroundRole()), 1.0))
        length = self._bar.pixels
        tick = self.TICK_LENGTH
        if self.orientation == Qt.Orientation.Horizontal:
            x = (self.width() - length) / 2
            y = self.height() - self.EDGE_MARGIN
            painter.drawLine(QPointF(x, y), QPointF(x + length, y))
            painter.drawLine(QPointF(x, y - tick), QPointF(x, y))
            painter.drawLine(QPointF(x + length, y - tick), QPointF(x + length, y))
            painter.drawText(self.rect().adjusted(0, 0, 0, -12),
                             Qt.AlignmentFlag.AlignCenter, self._bar.label)
        else:
            x = self.width() - self.EDGE_MARGIN
            y = (self.height() - length) / 2
            painter.drawLine(QPointF(x, y), QPointF(x, y + length))
            painter.drawLine(QPointF(x - tick, y), QPointF(x, y))
            painter.drawLine(QPointF(x - tick, y + length), QPointF(x, y + length))
            painter.drawText(self.rect().adjusted(2, 0, -20, 0),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             self._bar.label)
