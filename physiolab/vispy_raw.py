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


def sweep_segments(times, values, duration, head, scale=1.0):
    """Stable 2-pass left-to-right sweep geometry with previous-cycle persistence.

    Previous-cycle samples remain on the right of the advancing sweep head;
    current-cycle samples occupy the left. Segments may never cross a cycle
    boundary or join the old and new sweeps. Input amplitudes already have
    6-unit per-channel offsets applied by prepare_raw_window().
    """
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    if duration <= 0 or scale <= 0:
        raise ValueError('Sweep duration and vertical gain must be positive')
    if values.ndim != 2 or times.ndim != 1 or len(times) != len(values):
        raise ValueError('Mismatched sweep samples')
    if len(times) < 2 or not values.shape[1]:
        return (np.empty((0, 2), np.float32),
                np.empty((0, 4), np.float32))
    cycle = np.floor(times / duration).astype(np.int64)
    current = int(np.floor(head / duration))
    phase = float(head % duration)
    x = np.mod(times, duration)
    n = values.shape[1]
    offsets = 6. * np.arange(n)
    gain_values = offsets + scale * (values - offsets)
    lower, upper = -3., max(6.*n, 3.)
    normalized_y = (gain_values - lower) / (upper - lower)
    valid_samples = ((cycle == current)
                     | ((cycle == current - 1) & (x >= phase)))
    valid_samples &= times <= head + 1e-6
    pairs = (valid_samples[:-1] & valid_samples[1:]
             & (cycle[:-1] == cycle[1:])
             & (np.diff(times) <= max(.5, duration / 3.)))
    a = np.stack((x[:-1, None]/duration + np.zeros_like(normalized_y[:-1]),
                  normalized_y[:-1]), axis=-1)
    b = np.stack((x[1:, None]/duration + np.zeros_like(normalized_y[1:]),
                  normalized_y[1:]), axis=-1)
    valid = (pairs[:, None]
             & np.isfinite(a).all(axis=2)
             & np.isfinite(b).all(axis=2))
    segments = np.stack((a.transpose(1, 0, 2),
                         b.transpose(1, 0, 2)), axis=2).reshape(-1, 2, 2)
    keep = valid.T.ravel()
    segments = segments[keep]
    if not len(segments):
        return (np.empty((0, 2), np.float32),
                np.empty((0, 4), np.float32))
    colors = np.ones((len(segments)*2, 4), np.float32)
    return segments.reshape(-1, 2).astype(np.float32), colors


class VisPyRawPlot:
    """Incremental EEG/EDA/PPG GPU sweep using the common circular renderer."""

    def __init__(self, kind):
        from .vispy_plot_engine import VisPyPlotEngine
        self.kind = kind
        self.engine = VisPyPlotEngine(
            x_label='Sweep time (s)', y_label='Channels',
            size=(900, 350 if kind == 'EEG' else 300),
        )
        self.canvas = self.engine.canvas
        self.widget = self.engine.widget
        self.view = self.engine.view
        self.labels = []  # Legacy public attribute; channel names now live in Qt gutter.
        self.vertical_gain = 1.
        self.sweep_duration = 5.
        self.layers = {'raw': [], 'filtered': []}
        self._banks = {}
        self._configuration = None
        self._target_channels = 0
        self._pending_configuration = None
        self._pending_layers = None
        self._latest = -np.inf
        self._last_axis_duration = None
        # Keep the public layer attributes for widget smoke tests.
        self.raw_line = self.filtered_line = None

    def _drop_layers(self):
        for bank in getattr(self, '_banks', {}).values():
            bank.close()
        self._banks = {}
        self.layers = {'raw': [], 'filtered': []}
        self._configuration = None
        self._target_channels = 0
        self._latest = -np.inf
        self.raw_line = self.filtered_line = None

    def set_vertical_gain(self, gain):
        gain = float(gain)
        if not np.isfinite(gain) or gain <= 0:
            raise ValueError('Vertical gain must be finite and positive')
        if gain != self.vertical_gain:
            self.vertical_gain = gain
            for bank in getattr(self, '_banks', {}).values():
                bank.set_gain(gain)
            self.canvas.update()

    def reset(self):
        self._drop_layers()
        self.engine.set_channel_labels(())
        self.engine.sweep_cursor.visible = False
        self.canvas.update()

    def _ensure_layers(self, count, duration, rate):
        """Two drawables for all channels, no progressive channel construction."""
        from .batched_sweep import BatchedSweepBank
        config = (int(count), float(duration), float(rate))
        if self._configuration == config:
            return
        # Only replace banks when the display capacity truly changes.
        previous = getattr(self, '_banks', {})
        banks = {
            'raw': BatchedSweepBank(self.view.scene, count, duration, rate, '#db3232'),
            'filtered': BatchedSweepBank(self.view.scene, count, duration, rate, '#171717'),
        }
        for bank in banks.values():
            bank.visual.visible = False
            bank.set_gain(self.vertical_gain)
        self._banks = banks
        self._configuration = config
        self._target_channels = count
        self._latest = -np.inf
        for bank in previous.values():
            bank.close()
        self.raw_line = banks['raw'].visual
        self.filtered_line = banks['filtered'].visual

    def needs_history_replay(self, count, duration):
        if self._configuration is None:
            return True
        n, configured_duration, _ = self._configuration
        return n != count or configured_duration != duration

    def set_frame(self, frame, left, right, show_raw=True, show_filtered=True,
                  sweep_head=None, nominal_fs=None, max_points=2500):
        times, raw, filtered, _, _, names = frame
        duration = float(right-left)
        if duration <= 0:
            return
        n = raw.shape[1]
        if not len(times) or not n:
            return
        # The preparation worker uses fixed-clock decimation. Capture the
        # effective sample rate once per duration and preserve its bin phase.
        diffs = np.diff(times)
        diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
        if len(diffs):
            rate = float(max(1., round(1. / np.median(diffs), 3)))
        else:
            rate = self._configuration[2] if self._configuration else 1.
        if nominal_fs is not None and nominal_fs > 0:
            # Match the worker's fixed-clock decimation; never infer GPU
            # capacity from a short first frame or fallback grid samples.
            stride = max(1, int(np.ceil(
                float(nominal_fs) * (2. * duration) / max_points)))
            rate = float(nominal_fs) / stride
        elif self._configuration and self._configuration[:2] == (n, duration):
            rate = self._configuration[2]
        self._ensure_layers(n, duration, rate)
        lower, upper = -3., max(6. * n, 3.)
        for kind, values, enabled in (
            ('raw', raw, show_raw), ('filtered', filtered, show_filtered)
        ):
            bank = self._banks[kind]
            bank.visual.visible = bool(enabled)
            if bank.last_time >= float(times[-1]):
                continue
            bank.append(times, (values - lower) / (upper - lower))
        self.sweep_duration = duration
        self.engine.set_view(0., 1., 0., 1.)
        if duration != self._last_axis_duration:
            self.engine.set_axis_labels(duration=duration, bounds=(0., 1.))
            self._last_axis_duration = duration
        # Both the cursor and the erase boundary use the latest real sample.
        latest = float(times[-1])
        self._latest = max(self._latest, latest)
        self.engine.set_sweep_cursor((self._latest % duration)/duration)
        # Channel labels are rendered by a separate Qt gutter outside the
        # OpenGL viewport. No overlay can obscure the first EEG samples.
        channel_names = tuple(
            str(names[i]) if i < len(names) else f'Ch {i+1}'
            for i in range(n)
        )
        self.engine.set_channel_labels(channel_names)
        self.canvas.update()

    def close(self):
        self._drop_layers()
        self.engine.close()
