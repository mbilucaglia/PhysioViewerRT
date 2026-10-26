"""Optional GPU waveform presentation, inspired by Intheon StreamViewer LineVis.

This module is deliberately presentation-only: LSL receivers, calibrated raw
samples, signal processing, metric calculations and data history are unchanged.

VisPy is imported lazily so the standard pyqtgraph installation still works.
"""
from colorsys import hsv_to_rgb

import numpy as np
from .render_policy import RAW_DISPLAY_POLICY
from .display_units import ARBITRARY_UNIT


def trace_segments(times, values, left, right, lower=None, upper=None):
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
    default_lower, default_upper = RAW_DISPLAY_POLICY.bounds(v.shape[1])
    lower = default_lower if lower is None else lower
    upper = default_upper if upper is None else upper
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
    shared-policy channel offsets applied by prepare_raw_window().
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
    offsets = RAW_DISPLAY_POLICY.offsets(n)
    gain_values = offsets + scale * (values - offsets)
    lower, upper = RAW_DISPLAY_POLICY.bounds(n)
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
        self._trace_offsets = {}
        self._amplitude_step = None
        self._amplitude_unit = ARBITRARY_UNIT
        self.sweep_duration = 5.
        self.layers = {'raw': [], 'filtered': []}
        self._layer_pool = {'raw': [], 'filtered': []}
        self._configuration = None
        self._target_channels = 0
        self._pending_configuration = None
        self._pending_layers = None
        self._latest = -np.inf
        self._last_axis_duration = None
        self._warmup_failed = False
        # Keep the public layer attributes for widget smoke tests.
        self.raw_line = self.filtered_line = None

    def _drop_layers(self):
        closed = set()
        for collection in (self._layer_pool, self._pending_layers, self.layers):
            for group in (collection or {}).values():
                for layer in group:
                    if id(layer) not in closed:
                        layer.close()
                        closed.add(id(layer))
        self._layer_pool = {'raw': [], 'filtered': []}
        self._pending_layers = None
        self._pending_configuration = None
        self.layers = {'raw': [], 'filtered': []}
        self.raw_line = self.filtered_line = None
        self._configuration = None
        self._target_channels = 0
        self._latest = -np.inf
        self._trace_offsets = {}

    def set_vertical_gain(self, gain):
        gain = float(gain)
        if not np.isfinite(gain) or gain <= 0:
            raise ValueError('Vertical gain must be finite and positive')
        if gain != self.vertical_gain:
            self.vertical_gain = gain
            self._apply_gain()
            self.canvas.update()

    def _apply_gain(self):
        """Scale each existing trace around its channel offset in the shader.

        Changing amplitude never reallocates GPU sweep buffers or loses history.
        """
        count = len(self.layers['raw'])
        centers = RAW_DISPLAY_POLICY.normalized_centers(self._target_channels)
        for i in range(count):
            center = centers[i]
            for layer_name in ('raw', 'filtered'):
                self.layers[layer_name][i].set_gain(self.vertical_gain, center)
                self.layers[layer_name][i].set_offset(self.vertical_gain*self._trace_offsets.get((layer_name,i),0.))
        self._update_amplitude_ruler()

    def set_amplitude_units(self, step, unit):
        self._amplitude_step, self._amplitude_unit = float(step), unit
        self._update_amplitude_ruler()

    def set_sweep_head(self, head):
        """Use the shared display clock without altering sample timestamps."""
        if head is not None and np.isfinite(head):
            self._sweep_head = float(head)
            self.engine.set_sweep_cursor((float(head) % self.sweep_duration)
                                         / self.sweep_duration)

    def _update_amplitude_ruler(self):
        if getattr(self, '_amplitude_step', None) is not None and self._target_channels:
            self.engine.set_amplitude_range(
                self._amplitude_step * RAW_DISPLAY_POLICY.span(self._target_channels) / self.vertical_gain,
                self._amplitude_unit)

    def reset(self):
        # A new source discards samples, but can reuse already linked programs.
        for key, group in (self._pending_layers or {}).items():
            for layer in group:
                if layer not in self._layer_pool[key]:
                    layer.close()
        for group in self._layer_pool.values():
            for layer in group:
                layer.visual.visible = False
                ring = layer.ring
                layer.reconfigure(ring.duration, ring.rate, max_gap=ring.max_gap)
        self.layers = {'raw': [], 'filtered': []}
        self._configuration = self._pending_configuration = self._pending_layers = None
        self._target_channels = 0
        self._trace_offsets = {}
        self._latest = -np.inf
        self.raw_line = self.filtered_line = None
        self.engine.set_channel_labels(())
        self.engine.sweep_cursor.visible = False
        self.canvas.update()

    def invalidate_history(self):
        """Replay rescaled display data without replacing GPU programs."""
        for group in self.layers.values():
            for layer in group:
                ring = layer.ring
                layer.reconfigure(ring.duration, ring.rate, max_gap=ring.max_gap)
        self._latest = -np.inf

    def warm_channels(self, count, duration, nominal_fs):
        """Prepare one spare channel pair per idle tick, including driver linking.

        The offscreen draw uses empty geometry and never commits a display frame.
        Existing channel resources and their samples remain untouched.
        """
        if (self._warmup_failed or self._pending_layers is not None
                or len(self._layer_pool['raw']) >= count):
            return False
        from .incremental_sweep import IncrementalSweepLayer
        rate = RAW_DISPLAY_POLICY.display_rate(nominal_fs, duration)
        pair = []
        try:
            for key, color in (('raw', '#db3232'), ('filtered', '#171717')):
                layer = IncrementalSweepLayer(self.view.scene, duration, rate, color)
                pair.append(layer)
                layer.visual.visible = True
            # VisPy links programs lazily at draw time, not node construction.
            # A tiny framebuffer avoids reading back a full hidden plot image.
            self.canvas.render(size=(1, 1))
            self.engine.label_gutter.fontMetrics().height()
        except Exception:
            for layer in pair:
                layer.close()
            # Warmup is optional; normal first-use rendering remains available.
            import logging
            logging.getLogger(__name__).warning('Raw GPU warmup failed', exc_info=True)
            self._warmup_failed = True
            return False
        finally:
            for layer in pair:
                layer.visual.visible = False
        for key, layer in zip(('raw', 'filtered'), pair):
            self._layer_pool[key].append(layer)
        return True

    @property
    def reserved_channel_count(self):
        return len(self._layer_pool['raw'])

    def _ensure_layers(self, count, duration, rate):
        """Stage a new GPU configuration without displaying partial channels.

        Existing channels remain visible until the entire replacement scene
        has received history. Construct at most four channel pairs per frame.
        """
        from .incremental_sweep import IncrementalSweepLayer
        config = (count, float(duration), float(rate))
        if self._configuration == config and self._pending_layers is None:
            return self.layers, True
        if not hasattr(self, '_layer_pool'):
            self._layer_pool = {'raw': [], 'filtered': []}
        # Timebase changes reset storage, never the linked shader programs.
        if (self._pending_layers is None
                and all(len(self._layer_pool[key]) >= count
                        for key in ('raw', 'filtered'))):
            for key in ('raw', 'filtered'):
                for layer in self._layer_pool[key]:
                    layer.visual.visible = False
                self.layers[key] = self._layer_pool[key][:count]
                for layer in self.layers[key]:
                    layer.reconfigure(duration, rate)
            self._configuration = config
            self._target_channels = count
            self._latest = -np.inf
            self._apply_gain()
            self.raw_line = self.layers['raw'][0].visual if count else None
            self.filtered_line = self.layers['filtered'][0].visual if count else None
            return self.layers, True
        if self._pending_configuration != config:
            if self._pending_layers is not None:
                for key, group in self._pending_layers.items():
                    for layer in group:
                        if layer not in self._layer_pool[key]:
                            layer.close()
            self._pending_configuration = config
            self._pending_layers = {'raw': [], 'filtered': []}
        target = self._pending_layers
        built = len(target['raw'])
        for i in range(built, min(count, built + 4)):
            if i < len(self._layer_pool['raw']):
                raw_layer = self._layer_pool['raw'][i]
                filtered_layer = self._layer_pool['filtered'][i]
                raw_layer.reconfigure(duration, rate)
                filtered_layer.reconfigure(duration, rate)
            else:
                raw_layer = IncrementalSweepLayer(
                    self.view.scene, duration, rate, '#db3232')
                filtered_layer = IncrementalSweepLayer(
                    self.view.scene, duration, rate, '#171717')
            raw_layer.visual.visible = False
            filtered_layer.visual.visible = False
            target['raw'].append(raw_layer)
            target['filtered'].append(filtered_layer)
        return target, len(target['raw']) == count

    def _commit_layers(self, layers, config):
        """Atomically replace the visible sweep after every channel is ready."""
        old = self.layers
        self.layers = layers
        self._configuration = config
        self._target_channels = config[0]
        self._pending_layers = None
        self._pending_configuration = None
        for group in old.values():
            for layer in group:
                layer.visual.visible = False
        for key in ('raw', 'filtered'):
            for i, layer in enumerate(layers[key]):
                if i < len(self._layer_pool[key]):
                    if self._layer_pool[key][i] is not layer:
                        self._layer_pool[key][i].close()
                    self._layer_pool[key][i] = layer
                else:
                    self._layer_pool[key].append(layer)
        self._apply_gain()
        self.raw_line = layers['raw'][0].visual if layers['raw'] else None
        self.filtered_line = (
            layers['filtered'][0].visual if layers['filtered'] else None)

    def needs_history_replay(self, count, duration):
        """New GPU channels must receive full history, not just live tails."""
        if self._configuration is None:
            return True
        n, configured_duration, _ = self._configuration
        return (n != count or configured_duration != duration
                or self._pending_layers is not None)

    @property
    def channel_count(self):
        return self._target_channels

    @property
    def latest_sample_time(self):
        return self._latest

    @property
    def configured(self):
        return self._configuration is not None

    def history_needs_replay(self, count, duration):
        return self.needs_history_replay(count, duration)

    def set_frame(self, frame, left, right, show_raw=True, show_filtered=True,
                  sweep_head=None, nominal_fs=None,
                  max_points=RAW_DISPLAY_POLICY.max_points):
        times, raw, filtered, _, _, names = frame
        if sweep_head is not None and np.isfinite(sweep_head):
            stop = int(np.searchsorted(times, sweep_head, side='right'))
            times, raw, filtered = times[:stop], raw[:stop], filtered[:stop]
        duration = float(right-left)
        if duration <= 0:
            return
        n = raw.shape[1]
        if not len(times) or not n:
            return
        # The preparation worker uses fixed-clock decimation. Capture the
        # effective sample rate once per duration and preserve its bin phase.
        if nominal_fs is not None and nominal_fs > 0:
            # Match the worker's fixed-clock decimation; never infer GPU
            # capacity from a short first frame or fallback grid samples.
            rate = RAW_DISPLAY_POLICY.display_rate(nominal_fs, duration, max_points)
        elif self._configuration and self._configuration[:2] == (n, duration):
            rate = self._configuration[2]
        else:
            diffs = np.diff(times)
            diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
            rate = (float(max(1., round(1. / np.median(diffs), 3))) if len(diffs)
                    else self._configuration[2] if self._configuration else 1.)
        target_layers, ready = self._ensure_layers(n, duration, rate)
        # Only the new tail is processed. Previous samples supplied by the
        # worker are ignored in each ring after their first insertion.
        lower, upper = RAW_DISPLAY_POLICY.bounds(n)
        for layer_name, values, enabled in (
            ('raw', raw, show_raw), ('filtered', filtered, show_filtered)
        ):
            for i, layer in enumerate(target_layers[layer_name]):
                if self._pending_layers is None:
                    layer.visual.visible = bool(enabled)
                # Keep hidden layers current too: toggling Raw/Filtered back
                # on must not expose missing sweep bins or require a rebuild.
                if layer.ring.last_time >= float(times[-1]):
                    continue
                normalized = (values[:, i] - lower) / (upper-lower)
                layer.append(times, normalized)
        if self._pending_layers is not None:
            if not ready:
                return
            self._commit_layers(target_layers, (n, duration, rate))
            for layer_name, enabled in (('raw', show_raw),
                                        ('filtered', show_filtered)):
                for layer in self.layers[layer_name]:
                    layer.visual.visible = bool(enabled)
            self._latest = -np.inf
        self.sweep_duration = duration
        # Qt hosts labels outside the canvas; use the full waveform viewport.
        self.engine.set_view(0., 1., 0., 1.)
        if duration != self._last_axis_duration:
            self.engine.set_axis_labels(duration=duration, bounds=(0., 1.))
            self._last_axis_duration = duration
        # Data insertion uses source timestamps; only the cursor uses the
        # common presentation clock shared by the three raw panels.
        latest = float(times[-1])
        self._latest = max(self._latest, latest)
        self.set_sweep_head(self._latest if sweep_head is None else sweep_head)
        # Channel labels are rendered by a separate Qt gutter outside the
        # OpenGL viewport. No overlay can obscure the first EEG samples.
        # Peripheral DC drift should not detach a signal from its channel
        # label. Pan existing GPU geometry instead of rebuilding history or
        # changing stored samples/scales. Raw and processed DC are independent.
        if self.kind in ('PPG','EDA'):
            visible = times >= (self._latest if sweep_head is None else sweep_head)-duration
            if not np.any(visible):
                visible = np.ones(len(times),dtype=bool)
            for key,values in (('raw',raw),('filtered',filtered)):
                for i,layer in enumerate(self.layers[key]):
                    offset = -float(np.median(values[visible,i])-RAW_DISPLAY_POLICY.offsets(n)[i])/(upper-lower)
                    self._trace_offsets[key,i] = offset
                    layer.set_offset(self.vertical_gain*offset)
        channel_names = tuple(
            str(names[i]) if i < len(names) else f'Ch {i+1}'
            for i in range(n)
        )
        self.engine.set_channel_labels(channel_names)
        self.canvas.update()

    def close(self):
        self._drop_layers()
        self.engine.close()
