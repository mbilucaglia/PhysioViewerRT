"""Multichannel sweep rendered with one standard VisPy Line per modality.

The sweep rings preserve timestamp continuity. VisPy owns GPU buffers and
transfers via scene.visuals.Line.set_data; no application OpenGL shaders or
vertex-buffer calls are required.
"""
import numpy as np
from .incremental_sweep import SweepRing


def sweep_positions(rings, gain=1.):
    """Build disconnected [x, y] line segments for all channel rings.

    Ring geometry already excludes gaps and sweep-cycle crossings. Each
    segment is two vertices and is rendered using connect='segments'.
    Invalid ring slots remain off-canvas.
    """
    if not rings:
        return np.empty((0, 2), dtype=np.float32)
    n = len(rings)
    segments = np.stack([ring.positions for ring in rings], axis=0)
    result = np.ascontiguousarray(segments.reshape(-1, 2), dtype=np.float32)
    if gain != 1.:
        bottom, top = -3., max(6. * n, 3.)
        centers = (6. * np.arange(n, dtype=np.float32) - bottom) / (top - bottom)
        channel_centers = np.repeat(centers, rings[0].capacity * 2)
        valid = result[:, 0] >= 0.
        result[valid, 1] = (channel_centers[valid] +
                            gain * (result[valid, 1] - channel_centers[valid]))
    return result


def _line_class():
    from vispy import scene
    return scene.visuals.Line


class BatchedSweepBank:
    """One reusable high-level VisPy Line for all channels of a signal type."""

    def __init__(self, parent, channels, duration, rate, color):
        self.channels = int(channels)
        self.rings = [SweepRing(duration, rate) for _ in range(channels)]
        self.capacity = self.rings[0].capacity if self.rings else 0
        self.gain = 1.
        self.visual = _line_class()(
            pos=sweep_positions(self.rings), color=color, parent=parent,
            connect='segments', method='gl', antialias=False, width=1)

    def _upload(self):
        self.visual.set_data(pos=sweep_positions(self.rings, self.gain),
                             connect='segments')

    def set_gain(self, gain):
        self.gain = float(gain)
        self._upload()

    def append(self, times, matrix):
        matrix = np.asarray(matrix)
        if matrix.ndim != 2 or matrix.shape != (len(times), self.channels):
            raise ValueError('Expected [samples, channels] matrix')
        changed = 0
        for channel, ring in enumerate(self.rings):
            changed += len(ring.append(times, matrix[:, channel]))
        if changed:
            self._upload()
        return changed

    @property
    def last_time(self):
        return min((ring.last_time for ring in self.rings), default=-np.inf)

    def close(self):
        self.visual.parent = None
