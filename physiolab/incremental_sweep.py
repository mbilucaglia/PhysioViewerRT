"""Fixed-capacity sweep rings and partial GPU vertex uploads.

A display slot is tied to a fixed acquisition-time bin. Once a sample has
been painted its vertices remain unchanged until the sweep overwrites that
slot. Only a slot and its successor (the shared boundary) need updating.
"""
import numpy as np


class SweepRing:
    """One channel, one signal layer; independent of Qt and OpenGL."""

    def __init__(self, duration, rate, max_gap=None):
        self.duration = float(duration)
        self.rate = float(rate)
        if self.duration <= 0 or self.rate <= 0:
            raise ValueError('Sweep duration and rate must be positive')
        self.capacity = max(2, int(np.ceil(self.duration*self.rate)))
        self.max_gap = float(max_gap if max_gap is not None else max(.15, 3./self.rate))
        self.positions = np.full((self.capacity, 2, 2), -10., dtype=np.float32)
        self.stamps = np.full(self.capacity, -np.inf)
        self.values = np.full(self.capacity, np.nan)
        self.identities = np.full(self.capacity, np.iinfo(np.int64).min, dtype=np.int64)
        self.last_time = -np.inf
        self.last_id = np.iinfo(np.int64).min

    def _geometry(self, slot):
        """One segment from the preceding *time bin*, if it is contiguous."""
        index = int(self.identities[slot])
        previous = (slot-1) % self.capacity
        prior_id = int(self.identities[previous])
        if (index == np.iinfo(np.int64).min
                or prior_id != index - 1
                or not np.isfinite(self.values[slot])
                or not np.isfinite(self.values[previous])
                or self.stamps[slot] - self.stamps[previous] > self.max_gap
                or int(np.floor(self.stamps[slot]/self.duration))
                    != int(np.floor(self.stamps[previous]/self.duration))):
            return np.full((2, 2), -10., dtype=np.float32)
        return np.asarray([
            [(self.stamps[previous] % self.duration)/self.duration,
             self.values[previous]],
            [(self.stamps[slot] % self.duration)/self.duration,
             self.values[slot]],
        ], dtype=np.float32)

    def append(self, times, values):
        """Return only changed (slot, two-vertex segment) pairs.

        Idempotent with repeated historical frames. A backwards timestamp is
        ignored; changing the chosen display scaling must reset the ring.
        """
        t = np.asarray(times, dtype=float)
        v = np.asarray(values, dtype=float)
        if t.ndim != 1 or v.ndim != 1 or t.shape != v.shape:
            raise ValueError('One-dimensional timestamps/values required')
        changed = set()
        for when, value in zip(t, v):
            if not np.isfinite(when) or when <= self.last_time:
                continue
            identity = int(np.floor(when*self.rate + 1e-7))
            if identity <= self.last_id:
                self.last_time = float(when)
                continue
            slot = identity % self.capacity
            # Equal-age bins can contain multiple samples. The most recent
            # value is retained without changing unrelated GPU vertices.
            self.stamps[slot] = when
            self.values[slot] = value
            self.identities[slot] = identity
            self.last_time = float(when)
            self.last_id = identity
            changed.add(slot)
            changed.add((slot+1) % self.capacity)
        result = []
        for slot in sorted(changed):
            geometry = self._geometry(slot)
            self.positions[slot] = geometry
            result.append((slot, geometry.copy()))
        return result


@__import__('functools').lru_cache(maxsize=1)
def _incremental_visual_class():
    """Import VisPy only when the actual OpenGL backend is selected."""
    from functools import lru_cache
    from vispy import gloo
    from vispy.color import Color
    from vispy.visuals import Visual
    from vispy.scene.visuals import create_visual_node

    class PartialLineVisual(Visual):
        VERT = """
        attribute vec2 a_position;
        uniform vec4 u_color;
        uniform float u_point_size;
        varying vec4 v_color;
        void main() {
            gl_Position = $transform(vec4(a_position, 0., 1.));
            gl_PointSize = u_point_size;
            v_color = u_color;
        }
        """
        FRAG = """
        varying vec4 v_color;
        void main() { gl_FragColor = v_color; }
        """

        def __init__(self, capacity, color, mode='lines', point_size=5.):
            self.capacity = int(capacity)
            self.mode = mode
            self.vertices_per_slot = 1 if mode == 'points' else 2
            self._buffer = gloo.VertexBuffer(
                np.full((self.capacity*self.vertices_per_slot, 2),
                        -10., dtype=np.float32))
            Visual.__init__(self, vcode=self.VERT, fcode=self.FRAG)
            self.shared_program['a_position'] = self._buffer
            self.shared_program['u_color'] = Color(color).rgba
            self.shared_program['u_point_size'] = float(point_size)
            self._draw_mode = mode
            self.set_gl_state('translucent', depth_test=False)

        def _prepare_transforms(self, view):
            view.view_program.vert['transform'] = view.transforms.get_transform()

        def _prepare_draw(self, view):
            return True

        def _compute_bounds(self, axis, view):
            return (0., 1.)

        def patch(self, updates):
            if not updates:
                return
            # Merge consecutive ring slots into a single partial GPU write.
            slots = sorted(int(slot) for slot, _ in updates)
            start = previous = slots[0]
            by_slot = {int(slot): vertices for slot, vertices in updates}
            groups = []
            for slot in slots[1:]:
                if slot != previous + 1:
                    groups.append((start, previous + 1))
                    start = slot
                previous = slot
            groups.append((start, previous + 1))
            for first, end in groups:
                data = np.concatenate(
                    [np.asarray(by_slot[i], dtype=np.float32).reshape(
                        self.vertices_per_slot, 2) for i in range(first, end)],
                    axis=0)
                self._buffer.set_subdata(
                    np.ascontiguousarray(data),
                    offset=first*self.vertices_per_slot*2*4)
            self.update()

    return create_visual_node(PartialLineVisual)


class IncrementalSweepLayer:
    """One per-channel GL line node, with partial vertex uploads only."""

    def __init__(self, parent, duration, rate, color, max_gap=None,
                 mode='lines'):
        self.ring = SweepRing(duration, rate, max_gap)
        self.mode = mode
        VisualClass = _incremental_visual_class()
        self.visual = VisualClass(self.ring.capacity, color, mode=mode,
                                  parent=parent)

    def append(self, times, values):
        updates = self.ring.append(times, values)
        if self.mode == 'points':
            updates = [
                (slot, np.asarray([[
                    float(self.ring.stamps[slot] % self.ring.duration
                          / self.ring.duration),
                    float(self.ring.values[slot])]], dtype=np.float32)
                 if self.ring.identities[slot] != np.iinfo(np.int64).min
                 and np.isfinite(self.ring.values[slot])
                 else np.array([[-10., -10.]], dtype=np.float32))
                for slot, _ in updates
            ]
        self.visual.patch(updates)
        return len(updates)

    def close(self):
        self.visual.parent = None
