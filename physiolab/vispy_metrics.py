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
    """GPU metrics using the same white canvas and sweep as Raw Data."""

    def __init__(self, keys):
        import time
        from .vispy_plot_engine import VisPyPlotEngine
        self.keys = tuple(keys)
        self.engine = VisPyPlotEngine(
            x_label='Sweep time (s)', y_label='Metric value',
            size=(1000, 520))
        self.canvas = self.engine.canvas
        self.widget = self.engine.widget
        self.view = self.engine.view
        self.xaxis = self.engine.xaxis
        self.yaxis = self.engine.yaxis
        self.gridlines = self.engine.gridlines
        self.lines, self.points = {}, {}
        self._data = {}
        self._source = {}
        self._bounds = (-5., 0.)
        self._ylimits = (-1., 1.)
        self._last_rebuild = 0.
        for key, color in zip(self.keys, METRIC_COLORS):
            self.lines[key] = self.engine.line(color=color, width=2)
            self.points[key] = self.engine.markers()
            self.lines[key].visible = False
            self.points[key].visible = False

    def set_series(self, key, x, y, sample_x, sample_y,
                   visible=True, show_line=True, show_markers=True):
        self._source[key] = (
            np.asarray(x, dtype=float), np.asarray(y, dtype=float),
            np.asarray(sample_x, dtype=float), np.asarray(sample_y, dtype=float),
            bool(visible and show_line), bool(visible and show_markers),
        )
        self._last_rebuild = 0.
        self._render_series(key)
        self.canvas.update()

    def _render_series(self, key):
        from .vispy_plot_engine import VisPyPlotEngine
        x, y, mx, my, show_line, show_markers = self._source[key]
        left, head = self._bounds
        duration = head - left
        if duration <= 0:
            return
        line = (metric_sweep_segments(x, y, duration, head)
                if show_line else np.empty((0, 2), dtype=np.float32))
        pts = (metric_sweep_points(mx, my, duration, head)
               if show_markers else np.empty((0, 2), dtype=np.float32))
        self._data[key] = (line, pts)
        self.lines[key].visible = len(line) > 0
        if len(line):
            self.lines[key].set_data(pos=line, connect='segments')
        self.points[key].visible = len(pts) > 0
        if len(pts):
            self.points[key].set_data(
                pos=pts, face_color=METRIC_COLORS[self.keys.index(key)],
                edge_color=None, size=5)

    def set_xrange(self, left, right):
        import time
        self._bounds = (float(left), float(right))
        if right <= left:
            return
        # Move cursor smoothly without rebuilding all line vertices at 30fps.
        self.engine.set_sweep_cursor((right % (right-left))/(right-left))
        if time.monotonic() - self._last_rebuild >= .1:
            self._rebuild()
            self._last_rebuild = time.monotonic()

    def _rebuild(self):
        for key in self._source:
            self._render_series(key)
        low, high = metric_y_limits(self._data, 0., 1.)
        self._ylimits = (low, high)
        self.engine.set_view(0., 1., low, high)
        self.canvas.update()

    def refresh_axes(self):
        import time
        self._rebuild()
        self._last_rebuild = time.monotonic()

    def close(self):
        self.engine.close()
