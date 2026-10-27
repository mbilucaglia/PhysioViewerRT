"""GPU presentation of prepared metric curves, without physiological processing.

Uses the exact arrays from prepare_metric_curve(), including NaN gap markers.
Only this presentation layer depends on VisPy; the original pyqtgraph metric
plot remains available as a fallback.
"""
import numpy as np

from .metric_catalog import METRIC_PALETTE, metric_color

METRIC_COLORS = METRIC_PALETTE


class VisPyMetricPlot:
    """All Metrics series share the exact incremental GPU sweep used by Raw."""

    def __init__(self, keys):
        from .vispy_plot_engine import VisPyPlotEngine
        self.keys = tuple(keys)
        self.engine = VisPyPlotEngine(
            x_label='Sweep time (s)', y_label='Metric value', size=(1000, 520))
        self.canvas = self.engine.canvas
        self.widget = self.engine.widget
        self.view = self.engine.view
        self.xaxis = self.engine.xaxis
        self.yaxis = self.engine.yaxis
        self.lines = {}
        self.points = {}
        self._layers = {}
        self._bounds = (-5., 0.)
        self._duration = 5.
        self._latest = -np.inf
        self._y_limits = (-1., 1.)
        self._signature = None
        self._auto_y = True
        self._amplitude_unit = 'a.u.'
        self._amplitude_description = ''
        self._configure_layers()

    def set_amplitude_units(self, unit, description=''):
        self._amplitude_unit, self._amplitude_description = unit, description
        self._update_amplitude_ruler()

    def _update_amplitude_ruler(self):
        low, high = self._y_limits
        self.engine.set_amplitude_range(high-low, self._amplitude_unit)
        self.engine.amplitude_ruler.setToolTip(self._amplitude_description)

    def _configure_layers(self):
        from .incremental_sweep import IncrementalSweepLayer
        for index, key in enumerate(self.keys):
            if key in self._layers:
                self._reset_series(key)
                continue
            color = metric_color(index)
            # Fixed 20Hz output for interpolated metrics and their measured
            # markers; NaNs or missing observations never bridge gaps.
            line = IncrementalSweepLayer(
                self.view.scene, self._duration, 20., color, max_gap=1.1)
            dots = IncrementalSweepLayer(
                self.view.scene, self._duration, 20., color,
                max_gap=1.1, mode='points')
            line.visual.visible = False
            dots.visual.visible = False
            self._layers[key] = (line, dots)
            self.lines[key] = line.visual
            self.points[key] = dots.visual
        self._latest = -np.inf
        if self._auto_y:
            self._y_limits = (-1., 1.)
        self.engine.set_view(0., 1., *self._y_limits)
        self._update_amplitude_ruler()

    def _reset_series(self, key):
        # Reset CPU history and GPU geometry without creating new scene nodes
        # or shader programs. Existing visibility remains caller-controlled.
        for layer in self._layers[key]:
            layer.reconfigure(self._duration, 20., max_gap=1.1)

    def set_presentation_signature(self, signature):
        """Replay only when an established data transformation changes."""
        signature = tuple(signature)
        if self._signature != signature:
            initial = self._signature is None
            self._signature = signature
            if not initial:
                self._configure_layers()

    def set_series(self, key, x, y, sample_x, sample_y,
                   visible=True, show_line=True, show_markers=True):
        line, dots = self._layers[key]
        line_enabled = bool(visible and show_line)
        dots_enabled = bool(visible and show_markers)
        if ((not line.visual.visible and line_enabled and
             np.isfinite(line.ring.last_time))
                or (not dots.visual.visible and dots_enabled and
                    np.isfinite(dots.ring.last_time))):
            # Re-enabled series must replay retained data, otherwise samples
            # that arrived while the visual was hidden cannot be recovered.
            self._reset_series(key)
            line, dots = self._layers[key]
        line.visual.visible = line_enabled
        dots.visual.visible = dots_enabled
        if line_enabled:
            line.append(x, y)
        if dots_enabled:
            dots.append(sample_x, sample_y)
        if visible:
            finite = np.asarray(sample_y, dtype=float)
            finite = finite[np.isfinite(finite)]
            if not len(finite):
                finite = np.asarray(y, dtype=float)
                finite = finite[np.isfinite(finite)]
            if len(finite) and self._auto_y:
                low, high = self._y_limits
                candidate_low, candidate_high = float(np.min(finite)), float(np.max(finite))
                # Expand-only while live: autoscale must never make traces
                # jitter vertically on each new metric observation.
                pad = max(.1, (candidate_high-candidate_low)*.08)
                new_range = (min(low, candidate_low-pad),
                             max(high, candidate_high+pad))
                if new_range != self._y_limits:
                    self._y_limits = new_range
                    self.engine.set_view(0., 1., *new_range)
                    self.engine.set_axis_labels(bounds=new_range)
                    self._update_amplitude_ruler()
            points = np.asarray(sample_x, dtype=float)
            points = points[np.isfinite(points)]
            if len(points):
                self._latest = max(self._latest, float(points[-1]))
        self.canvas.update()

    @property
    def y_range(self):
        return self._y_limits

    def set_y_range(self, low, high):
        if not np.isfinite([low, high]).all() or high <= low:
            raise ValueError('Metric vertical bounds must be finite and increasing')
        self._y_limits = (float(low), float(high))
        self.engine.set_view(0., 1., *self._y_limits)
        self.engine.set_axis_labels(bounds=self._y_limits)
        self._update_amplitude_ruler()
        self.canvas.update()

    def set_y_auto(self, enabled):
        self._auto_y = bool(enabled)
        if enabled:
            self.fit_y()

    def zoom_y(self, factor):
        if not np.isfinite(factor) or factor <= 0:
            raise ValueError('Vertical zoom factor must be positive')
        self._auto_y = False
        low, high = self._y_limits
        center, half = (low+high)/2., (high-low)*factor/2.
        self.set_y_range(center-half, center+half)

    def fit_y(self):
        values = []
        for pair in self._layers.values():
            for layer in pair:
                if layer.visual.visible:
                    ring = layer.ring
                    visible = (np.isfinite(ring.values)
                               & (ring.stamps >= self._latest-self._duration)
                               & (ring.stamps <= self._latest))
                    if np.any(visible):
                        values.append(ring.values[visible])
        if values:
            values = np.concatenate(values)
            low, high = float(np.min(values)), float(np.max(values))
            pad = max(.1, (high-low)*.08)
            self.set_y_range(low-pad, high+pad)
        else:
            self.set_y_range(-1., 1.)

    def set_xrange(self, left, right):
        duration = float(right-left)
        if duration <= 0:
            return
        self._bounds = (float(left), float(right))
        self.engine.set_axis_labels(duration=duration)
        if not np.isclose(duration, self._duration):
            self._duration = duration
            self._configure_layers()
        # Cursor remains at the last true measurement, never ahead of data.
        if np.isfinite(self._latest):
            self.engine.set_sweep_cursor(
                (self._latest % self._duration)/self._duration)

    def refresh_axes(self):
        if np.isfinite(self._latest):
            for _, dots in self._layers.values():
                dots.expire_points(self._latest)
            self.engine.set_sweep_cursor(
                (self._latest % self._duration)/self._duration)
        self.canvas.update()

    def close(self):
        for pair in self._layers.values():
            for layer in pair:
                layer.close()
        self.engine.close()
