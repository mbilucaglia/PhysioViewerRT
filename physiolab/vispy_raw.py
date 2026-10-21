"""Optional GPU waveform presentation, inspired by Intheon StreamViewer LineVis.

This module is deliberately presentation-only: LSL receivers, calibrated raw
samples, signal processing, metric calculations and data history are unchanged.

VisPy is imported lazily so the standard pyqtgraph installation still works.
"""
from colorsys import hsv_to_rgb

import numpy as np


def trace_segments(times, values, left, right, lower=-3.0, upper=50.0):
    """Make one batched GL line geometry for all channels.

    Input `values` is [samples, channels], pre-scaled by raw_render.py.
    Output positions and colors are arrays suitable for one VisPy Line visual.
    Every channel uses independently disconnected line segments; no diagonal
    jump between channels, or across NaN/data gaps.
    """
    t = np.asarray(times, dtype=float)
    v = np.asarray(values, dtype=float)
    if v.ndim != 2 or t.ndim != 1 or v.shape[0] != len(t):
        raise ValueError('Waveform and timestamp dimensions do not match')
    if right <= left or upper <= lower:
        raise ValueError('Invalid waveform viewport bounds')
    if len(t) < 2 or not v.shape[1]:
        return np.empty((0, 2), dtype=np.float32), np.empty((0, 4), dtype=np.float32)
    x = (t - float(left)) / float(right - left)
    y = (v - float(lower)) / float(upper - lower)
    # Shape [channel, consecutive pair, endpoint, xy]. Each pair is an
    # independent GL segment; the GPU receives just one visual per modality.
    a = np.stack((x[:-1, None] + np.zeros_like(y[:-1]), y[:-1]), axis=-1)
    b = np.stack((x[1:, None] + np.zeros_like(y[1:]), y[1:]), axis=-1)
    valid = (np.isfinite(a).all(axis=-1) & np.isfinite(b).all(axis=-1)
             & (np.maximum(a[..., 0], b[..., 0]) >= 0)
             & (np.minimum(a[..., 0], b[..., 0]) <= 1))
    positions = np.stack((a.transpose(1, 0, 2), b.transpose(1, 0, 2)), axis=2)
    flat = positions.reshape(-1, 2, 2)
    good = valid.T.ravel()
    flat = flat[good]
    if not len(flat):
        return np.empty((0, 2), dtype=np.float32), np.empty((0, 4), dtype=np.float32)
    channel_ids = np.repeat(np.arange(v.shape[1], dtype=int), len(t)-1)[good]
    colors = np.zeros((len(flat)*2, 4), dtype=np.float32)
    unique, inverse = np.unique(channel_ids, return_inverse=True)
    palette = np.asarray([
        (*hsv_to_rgb(float(index % max(v.shape[1], 3)) / max(v.shape[1], 3),
                     0.77, 0.98), 0.92)
        for index in unique
    ], dtype=np.float32)
    colors[0::2] = palette[inverse]
    colors[1::2] = palette[inverse]
    return flat.reshape(-1, 2).astype(np.float32), colors


class VisPyRawPlot:
    """A GPU canvas for one raw modality; only accessed by the Qt GUI thread."""

    def __init__(self, kind):
        # Lazy import: pyqtgraph remains default, without mandatory OpenGL deps.
        from vispy import scene
        self.kind = kind
        self.canvas = scene.SceneCanvas(
            keys=None, show=False, bgcolor='#15191f', size=(900, 330),
            app='pyside6',
        )
        self.widget = self.canvas.native
        self.view = self.canvas.central_widget.add_view()
        self.view.camera = scene.PanZoomCamera(rect=(0, 0, 1, 1), aspect=None)
        self.view.camera.interactive = False
        # A single GL draw item per raw / filtered layer, not one Qt curve
        # per channel. Acquisition and normalization stay in existing modules.
        self.raw_line = scene.visuals.Line(
            parent=self.view.scene, method='gl', connect='segments',
            antialias=False, width=1,
        )
        self.filtered_line = scene.visuals.Line(
            parent=self.view.scene, method='gl', connect='segments',
            antialias=False, width=1,
        )

    def reset(self):
        self.raw_line.visible = False
        self.filtered_line.visible = False
        self.canvas.update()

    def set_frame(self, frame, left, right, show_raw=True, show_filtered=True):
        times, raw, filtered, _, _, _ = frame
        lower, upper = -3., max(6. * raw.shape[1], 3.)
        for layer, enabled, data in (
            (self.raw_line, show_raw, raw),
            (self.filtered_line, show_filtered, filtered),
        ):
            if not enabled:
                layer.visible = False
                continue
            positions, colors = trace_segments(
                times, data, left, right, lower, upper
            )
            layer.visible = bool(len(positions))
            if len(positions):
                layer.set_data(pos=positions, color=colors, connect='segments')
        self.canvas.update()

    def close(self):
        self.canvas.close()
