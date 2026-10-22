"""Batched incremental EEG sweep: two GPU drawables regardless of channel count.

Each signal type owns one vertex buffer; channel segments occupy fixed,
non-overlapping ranges. Ring geometry and timestamp decisions remain pure
NumPy in SweepRing. VisPy imports occur only when a GPU canvas is created.
"""
from functools import lru_cache
import numpy as np
from .incremental_sweep import SweepRing


@lru_cache(maxsize=1)
def _batch_visual():
    from vispy import gloo
    from vispy.color import Color
    from vispy.visuals import Visual
    from vispy.scene.visuals import create_visual_node

    class BatchedLineVisual(Visual):
        VERT = """
        attribute vec3 a_position;
        uniform float u_gain;
        uniform vec4 u_color;
        varying vec4 v_color;
        void main() {
            vec3 p = a_position;
            p.y = p.z + u_gain * (p.y - p.z);
            gl_Position = $transform(vec4(p.xy, 0., 1.));
            v_color = u_color;
        }
        """
        FRAG = """
        varying vec4 v_color;
        void main() { gl_FragColor = v_color; }
        """

        def __init__(self, capacity, color):
            self.capacity = int(capacity)
            self._buffer = gloo.VertexBuffer(
                np.full((capacity * 2, 3), -10., dtype=np.float32))
            super().__init__(vcode=self.VERT, fcode=self.FRAG)
            self.shared_program['a_position'] = self._buffer
            self.shared_program['u_gain'] = 1.
            self.shared_program['u_color'] = Color(color).rgba
            self.set_gl_state('translucent', depth_test=False)

        def _prepare_transforms(self, view):
            view.view_program.vert['transform'] = view.transforms.get_transform()

        def _prepare_draw(self, view):
            return True

        def _compute_bounds(self, axis, view):
            return (0., 1.)

        def set_gain(self, gain):
            self.shared_program['u_gain'] = float(gain)
            self.update()

        def patch(self, first_vertex, data):
            if not len(data):
                return
            self._buffer.set_subdata(
                np.ascontiguousarray(data, dtype=np.float32),
                offset=int(first_vertex))
            self.update()

    return create_visual_node(BatchedLineVisual)


class BatchedSweepBank:
    """A single drawable holding all channels of one signal modality."""

    def __init__(self, parent, channels, duration, rate, color):
        self.channels = int(channels)
        self.rings = [SweepRing(duration, rate) for _ in range(channels)]
        self.capacity = self.rings[0].capacity if self.rings else 0
        self.visual = _batch_visual()(self.channels * self.capacity,
                                      color, parent=parent)

    def set_gain(self, gain):
        self.visual.set_gain(gain)

    def append(self, times, matrix):
        """Update only changed channel slots; no per-channel drawables."""
        matrix = np.asarray(matrix)
        if matrix.ndim != 2 or matrix.shape != (len(times), self.channels):
            raise ValueError('Expected [samples, channels] matrix')
        updates = 0
        for channel, ring in enumerate(self.rings):
            changed = ring.append(times, matrix[:, channel])
            if not changed:
                continue
            # The shader scales each sample around its channel's own center.
            # The third attribute is the per-channel normalized baseline.
            bottom = -3.
            top = max(6. * self.channels, 3.)
            baseline = (6. * channel - bottom) / (top - bottom)
            for slot, geometry in changed:
                positions = np.empty((2, 3), dtype=np.float32)
                positions[:, :2] = geometry
                positions[:, 2] = baseline
                self.visual.patch(2 * (channel * self.capacity + slot),
                                  positions)
                updates += 1
        return updates

    @property
    def last_time(self):
        return min((ring.last_time for ring in self.rings), default=-np.inf)

    def close(self):
        self.visual.parent = None
