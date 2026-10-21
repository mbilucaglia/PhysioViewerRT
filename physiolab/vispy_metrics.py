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


class VisPyMetricPlot:
    """One axes-equipped VisPy canvas with five independent metric series."""

    def __init__(self, keys):
        from .vispy_plot_engine import VisPyPlotEngine
        self.keys = tuple(keys)
        self.engine = VisPyPlotEngine(
            x_label='Elapsed session time (s)', y_label='Metric value',
            size=(1000, 520),
        )
        self.canvas = self.engine.canvas
        self.widget = self.engine.widget
        self.view = self.engine.view
        self.xaxis = self.engine.xaxis
        self.yaxis = self.engine.yaxis
        self.gridlines = self.engine.gridlines
        self.lines = {}
        self.points = {}
        self._data = {}
        for key, color in zip(self.keys, METRIC_COLORS):
            self.lines[key] = self.engine.line(color=color, width=2)
            self.points[key] = self.engine.markers()
            self.lines[key].visible = False
            self.points[key].visible = False
        self._bounds = (-5., 0.)
        self._ylimits = (-1., 1.)

    def set_series(self, key, x, y, sample_x, sample_y,
                   visible=True, show_line=True, show_markers=True):
        line = metric_segments(x, y) if visible and show_line else np.empty((0, 2), dtype=np.float32)
        pts = metric_points(sample_x, sample_y) if visible and show_markers else np.empty((0, 2), dtype=np.float32)
        self._data[key] = (line, pts)
        visual = self.lines[key]
        visual.visible = len(line) > 0
        if len(line):
            visual.set_data(pos=line, connect='segments')
        marker = self.points[key]
        marker.visible = len(pts) > 0
        if len(pts):
            marker.set_data(pos=pts, face_color=METRIC_COLORS[self.keys.index(key)],
                            edge_color=None, size=5)
        self.canvas.update()

    def set_xrange(self, left, right):
        self._bounds = (float(left), float(right))
        self._update_camera()

    def _update_camera(self):
        left, right = self._bounds
        if right <= left:
            return
        self._ylimits = metric_y_limits(self._data, left, right)
        low, high = self._ylimits
        # Assign the explicit viewport; set_range() queries bounds of empty
        # Markers visuals on startup and raises before any metrics arrive.
        self.engine.set_view(left, right, low, high)

    def refresh_axes(self):
        self._update_camera()

    def close(self):
        self.engine.close()
