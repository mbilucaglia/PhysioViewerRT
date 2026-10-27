"""Independent sparse-marker oracle for tests; never used by runtime rendering."""
import numpy as np

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


