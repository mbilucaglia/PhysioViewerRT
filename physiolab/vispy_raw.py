"""Optional GPU waveform presentation, inspired by Intheon StreamViewer LineVis.

This module is deliberately presentation-only: LSL receivers, calibrated raw
samples, signal processing, metric calculations and data history are unchanged.

VisPy is imported lazily so the standard pyqtgraph installation still works.
"""

import numpy as np
from .render_policy import RAW_DISPLAY_POLICY
from .display_units import ARBITRARY_UNIT
from .render_contracts import PreparedFrame


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
        self._update_amplitude_ruler()

    def set_amplitude_units(self, step, unit):
        self._amplitude_step, self._amplitude_unit = float(step), unit
        self._update_amplitude_ruler()

    def set_sweep_head(self, head):
        """Use the shared display clock without altering sample timestamps."""
        if head is not None and np.isfinite(head) and np.isfinite(self._latest):
            # A shared viewport is not evidence that this modality has drawn
            # samples that far. Pin its marker to its own committed trace tip.
            self._sweep_head = min(float(head),self._latest)
            self.engine.set_sweep_cursor((self._sweep_head % self.sweep_duration)
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
                # Retired banks are invisible and reconfigured before reuse in
                # _ensure_layers. Missing sources must not allocate/upload all
                # of their retained buffers on every healthy-source draw tick.
        self.layers = {'raw': [], 'filtered': []}
        self._configuration = self._pending_configuration = self._pending_layers = None
        self._target_channels = 0
        self._latest = -np.inf
        self.raw_line = self.filtered_line = None
        self.engine.set_channel_labels(())
        self.engine.sweep_cursor.visible = False
        self.canvas.update()

    def invalidate_history(self):
        """Invalidate staging only. Active geometry stays intact until commit."""
        self._pending_layers = None
        self._pending_configuration = None
        self._configuration = None

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
        if self._pending_configuration != config:
            self._pending_configuration = config
            self._pending_layers = {'raw': [], 'filtered': []}
        target = self._pending_layers
        built = len(target['raw'])
        spare_count=min(sum(layer not in self.layers[key] and layer not in target[key]
                            for layer in self._layer_pool[key]) for key in ('raw','filtered'))
        limit=count if spare_count>=count-built else min(count,built+4)
        for i in range(built, limit):
            for key, color in (('raw','#db3232'),('filtered','#171717')):
                spare = next((layer for layer in self._layer_pool[key]
                              if layer not in self.layers[key] and layer not in target[key]), None)
                if spare is None:
                    spare = IncrementalSweepLayer(self.view.scene,duration,rate,color)
                    self._layer_pool[key].append(spare)
                else:
                    spare.reconfigure(duration,rate)
                spare.visual.visible = False
                target[key].append(spare)
        return target, len(target['raw']) == count

    def _commit_layers(self, layers, config):
        """Swap disjoint generations after all replacement channels have data."""
        for group in self.layers.values():
            for layer in group: layer.visual.visible = False
        self.layers = layers
        self._configuration = config
        self._target_channels = config[0]
        self._pending_layers = self._pending_configuration = None
        self._apply_gain()
        self.raw_line = layers['raw'][0].visual if layers['raw'] else None
        self.filtered_line = layers['filtered'][0].visual if layers['filtered'] else None

    def needs_history_replay(self, count, duration):
        """New GPU channels must receive full history, not just live tails."""
        if self._configuration is None:
            return True
        n, configured_duration, _ = self._configuration
        return (n != count or configured_duration != duration
                or not np.isfinite(self._latest)
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
        # Public set_frame remains compatible with diagnostic fixtures from
        # before the controller. Runtime present() always supplies PreparedFrame.
        if not isinstance(frame,PreparedFrame): frame=PreparedFrame(*frame)
        times,raw,filtered,names=frame.times,frame.raw,frame.filtered,frame.names
        connect = frame.connect
        if sweep_head is not None and np.isfinite(sweep_head):
            stop = int(np.searchsorted(times, sweep_head, side='right'))
            times, raw, filtered = times[:stop], raw[:stop], filtered[:stop]
            if connect is not None: connect = connect[:stop]
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
            rate = float(nominal_fs)
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
                layer.append(times, normalized, connect=connect)
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
        channel_names = tuple(
            str(names[i]) if i < len(names) else f'Ch {i+1}'
            for i in range(n)
        )
        self.engine.set_channel_labels(channel_names)
        self.canvas.update()

    def present(self, frame, view, fs):
        if frame is None:
            self.reset()
            self.sweep_duration=view.duration
            self.engine.set_axis_labels(duration=view.duration,bounds=(0.,1.))
            return True
        self.set_amplitude_units(float(frame.scales[0]),view.unit)
        self.set_vertical_gain(view.gain)
        self.set_frame(frame,0.,view.duration,show_raw=view.show_raw,
                       show_filtered=view.show_filtered,sweep_head=view.right,nominal_fs=fs)
        return not self.history_needs_replay(view.channels,view.duration)

    def close(self):
        self._drop_layers()
        self.engine.close()
