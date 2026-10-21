"""GPU presentation of prepared metric curves, without physiological processing.

Uses the exact arrays from prepare_metric_curve(), including NaN gap markers.
Only this presentation layer depends on VisPy; the original pyqtgraph metric
plot remains available as a fallback.
"""
import numpy as np

METRIC_COLORS = ('#e69f00', '#56b4e9', '#009e73', '#cc79a7', '#d55e00')


def metric_segments(times, values):
    """Return disjoint GL line-pair vertices, respecting missing observations."""
    x, y = np.asarray(times, dtype=float), np.asarray(values, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.shape != y.shape:
        raise ValueError('Metric x/y arrays must be matching vectors')
    if len(x) < 2:
        return np.empty((0, 2), dtype=np.float32)
    valid = (np.isfinite(x[:-1]) & np.isfinite(y[:-1])
             & np.isfinite(x[1:]) & np.isfinite(y[1:]))
    if not np.any(valid):
        return np.empty((0, 2), dtype=np.float32)
    start = np.column_stack((x[:-1], y[:-1]))[valid]
    stop = np.column_stack((x[1:], y[1:]))[valid]
    return np.stack((start, stop), axis=1).reshape(-1, 2).astype(np.float32)


def metric_points(times, values):
    x, y = np.asarray(times, dtype=float), np.asarray(values, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.shape != y.shape:
        raise ValueError('Metric point arrays must be matching vectors')
    valid = np.isfinite(x) & np.isfinite(y)
    return np.column_stack((x[valid], y[valid])).astype(np.float32)


def metric_y_limits(curves, left, right):
    """Robust visible-window y limits shared across enabled metric series."""
    finite = []
    for line, points in curves.values():
        for data in (line, points):
            if len(data):
                mask = ((data[:, 0] >= left) & (data[:, 0] <= right)
                        & np.isfinite(data[:, 1]))
                if np.any(mask):
                    finite.append(data[mask, 1])
    if not finite:
        return (-1., 1.)
    values = np.concatenate(finite)
    lo, hi = float(np.min(values)), float(np.max(values))
    pad = max((hi-lo) * .08, .1 if hi == lo else 1e-6)
    return (lo-pad, hi+pad)


def metric_sweep_segments(times, values, duration, head):
    """Split metric lines by cycles; retain old right-hand trace."""
    x, y = np.asarray(times, dtype=float), np.asarray(values, dtype=float)
    if duration <= 0:
        raise ValueError('Duration must be positive')
    if x.ndim != 1 or y.ndim != 1 or x.shape != y.shape:
        raise ValueError('Metric x/y arrays must be matching vectors')
    if len(x) < 2:
        return np.empty((0, 2), dtype=np.float32)
    # Nonfinite samples are gaps; calculate cycle IDs only for finite x.
    finite = np.isfinite(x)
    safe = np.where(finite, x, 0.)
    cycles = np.floor(safe/duration).astype(np.int64)
    current = int(np.floor(head/duration))
    phase = head % duration
    px = np.mod(safe, duration) / duration
    visible = finite & np.isfinite(y) & (x <= head + 1e-6)
    visible &= ((cycles == current)
                | ((cycles == current-1) & (px >= phase/duration)))
    pairs = visible[:-1] & visible[1:] & (cycles[:-1] == cycles[1:])
    if not np.any(pairs):
        return np.empty((0, 2), dtype=np.float32)
    begin = np.column_stack((px[:-1], y[:-1]))[pairs]
    end = np.column_stack((px[1:], y[1:]))[pairs]
    return np.stack((begin, end), axis=1).reshape(-1, 2).astype(np.float32)


def metric_sweep_points(times, values, duration, head):
    x, y = np.asarray(times, dtype=float), np.asarray(values, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.shape != y.shape:
        raise ValueError('Metric points must be matching vectors')
    if duration <= 0:
        raise ValueError('Duration must be positive')
    finite = np.isfinite(x) & np.isfinite(y)
    if not np.any(finite):
        return np.empty((0, 2), dtype=np.float32)
    x, y = x[finite], y[finite]
    current = np.floor(head/duration)
    cycles = np.floor(x/duration)
    phases = (x % duration)/duration
    valid = (x <= head + 1e-6) & (
        (cycles == current)
        | ((cycles == current-1) & (phases >= (head % duration)/duration))
    )
    return np.column_stack((phases[valid], y[valid])).astype(np.float32)


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
        self.gridlines = self.engine.gridlines
        self.lines = {}
        self.points = {}
        self._layers = {}
        self._bounds = (-5., 0.)
        self._duration = 5.
        self._latest = -np.inf
        self._y_limits = (-1., 1.)
        self._signature = None
        self._configure_layers()

    def _configure_layers(self):
        from .incremental_sweep import IncrementalSweepLayer
        for layer_pair in self._layers.values():
            for layer in layer_pair:
                layer.close()
        self._layers = {}
        for key, color in zip(self.keys, METRIC_COLORS):
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
        self._y_limits = (-1., 1.)
        self.engine.set_view(0., 1., *self._y_limits)

    def set_presentation_signature(self, signature):
        """Rebuild only when data transformation settings change."""
        signature = tuple(signature)
        if self._signature != signature:
            self._signature = signature
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
            self._configure_layers()
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
            if len(finite):
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
            points = np.asarray(sample_x, dtype=float)
            points = points[np.isfinite(points)]
            if len(points):
                self._latest = max(self._latest, float(points[-1]))
        self.canvas.update()

    def set_xrange(self, left, right):
        duration = float(right-left)
        if duration <= 0:
            return
        self._bounds = (float(left), float(right))
        if not np.isclose(duration, self._duration):
            self._duration = duration
            self._configure_layers()
        # Cursor remains at the last true measurement, never ahead of data.
        if np.isfinite(self._latest):
            self.engine.set_sweep_cursor(
                (self._latest % self._duration)/self._duration)

    def refresh_axes(self):
        if np.isfinite(self._latest):
            self.engine.set_sweep_cursor(
                (self._latest % self._duration)/self._duration)
        self.canvas.update()

    def close(self):
        for pair in self._layers.values():
            for layer in pair:
                layer.close()
        self.engine.close()
