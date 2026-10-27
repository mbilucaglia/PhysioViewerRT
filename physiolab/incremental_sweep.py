"""Fixed-capacity sweep rings and partial GPU vertex uploads.

A display slot is tied to a fixed acquisition-time bin. Once a sample has
been painted its vertices remain unchanged until the sweep overwrites that
slot. Only the segment ending at the arriving sample is replaced; the next
old segment remains visible until its own replacement arrives.
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
        self.bin_phase = None
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

    def append(self, times, values, connect=None):
        """Return only changed (slot, two-vertex segment) pairs.

        Idempotent with repeated historical frames. A backwards timestamp is
        ignored; changing the chosen display scaling must reset the ring.
        """
        t = np.asarray(times, dtype=float)
        v = np.asarray(values, dtype=float)
        if t.ndim != 1 or v.ndim != 1 or t.shape != v.shape:
            raise ValueError('One-dimensional timestamps/values required')
        if connect is not None:
            return self._append_selected(t,v,np.asarray(connect,dtype=bool))
        # NumPy handles replay batches without Python work per sample/channel
        # on the GUI thread. Preserve the first sample in each advancing bin.
        finite = np.isfinite(t)
        t, v = t[finite], v[finite]
        if not len(t):
            return []
        prior = np.maximum.accumulate(np.r_[self.last_time, t])[:-1]
        advancing = t > prior
        t, v = t[advancing], v[advancing]
        if not len(t):
            return []
        self.last_time = float(t[-1])
        # Center bins on the nominal sample clock. Flooring puts correctly
        # timed samples on bin edges: tiny +/- timestamp jitter can then
        # produce IDs 0, 0, 2, 2, ... and no consecutive drawable segments.
        # Geometry still uses the measured timestamps, without resampling.
        if self.bin_phase is None:
            first_tick = float(t[0]*self.rate)
            self.bin_phase = first_tick-np.rint(first_tick)
        # A source may start halfway between nominal bins. Anchor its phase
        # once; micro-jitter must not alternate duplicate and skipped bins.
        identities = np.rint(t*self.rate-self.bin_phase).astype(np.int64)
        first = np.r_[identities[0] > self.last_id,
                      np.diff(identities) > 0]
        first &= identities > self.last_id
        identities, t, v = identities[first], t[first], v[first]
        if not len(t):
            return []
        self.last_id = int(identities[-1])
        slots = identities % self.capacity
        # A replay can span multiple cycles; keep the newest write per slot.
        _, reverse_indices = np.unique(slots[::-1], return_index=True)
        latest = len(slots) - 1 - reverse_indices
        target = slots[latest]
        # Capture each segment's own preceding sample before ring writes
        # overwrite a preceding slot from the older cycle. A full replay may
        # include both cycles; find predecessors in the input batch first.
        previous = (target-1) % self.capacity
        prior_ids = self.identities[previous].copy()
        prior_times = self.stamps[previous].copy()
        prior_values = self.values[previous].copy()
        expected = identities[latest]-1
        indices = np.searchsorted(identities, expected)
        safe = np.minimum(indices, len(identities)-1)
        found = (indices < len(identities)) & (identities[safe] == expected)
        prior_ids[found] = identities[safe[found]]
        prior_times[found] = t[safe[found]]
        prior_values[found] = v[safe[found]]
        self.stamps[target] = t[latest]
        self.values[target] = v[latest]
        self.identities[target] = identities[latest]
        changed = target
        valid = (
            (prior_ids == expected)
            & np.isfinite(self.values[changed])
            & np.isfinite(prior_values)
            & (self.stamps[changed]-prior_times <= self.max_gap)
            & (np.floor(self.stamps[changed]/self.duration)
               == np.floor(prior_times/self.duration)))
        geometry = np.full((len(changed), 2, 2), -10., dtype=np.float32)
        good = changed[valid]
        geometry[valid, 0, 0] = (prior_times[valid] % self.duration)/self.duration
        geometry[valid, 0, 1] = prior_values[valid]
        geometry[valid, 1, 0] = (self.stamps[good] % self.duration)/self.duration
        geometry[valid, 1, 1] = self.values[good]
        self.positions[changed] = geometry
        stale=self.discard_before(self.last_time-self.duration-1e-9)
        return list(zip(changed.tolist(), self.positions[changed])) + [
            (int(slot),self.positions[slot]) for slot in stale if slot not in changed]

    def _append_selected(self,t,v,connect):
        """Original sample slots with explicit reduction/gap topology.

        Extrema timestamps are irregular after reduction. Never decimate a
        second time or infer missing samples from their display-bin spacing.
        """
        if connect.shape!=t.shape: raise ValueError('Edge mask must match samples')
        keep=np.isfinite(t)&(t>self.last_time)
        selected=np.flatnonzero(keep)
        if not len(selected): return []
        if self.bin_phase is None:
            tick=t[selected[0]]*self.rate; self.bin_phase=tick-np.rint(tick)
        identities=np.rint(t[selected]*self.rate-self.bin_phase).astype(np.int64)
        slots=identities%self.capacity
        _,reverse=np.unique(slots[::-1],return_index=True)
        newest=len(slots)-1-reverse
        rows=selected[newest]; target=slots[newest]
        prior_rows=np.maximum(0,rows-1)
        pt=t[prior_rows].copy(); pv=v[prior_rows].copy()
        first=rows==0
        pt[first]=getattr(self,'_selected_time',-np.inf)
        pv[first]=getattr(self,'_selected_value',np.nan)
        valid=(connect[rows]&np.isfinite(v[rows])&np.isfinite(pv)&(pt<t[rows])
               &(np.floor(pt/self.duration)==np.floor(t[rows]/self.duration)))
        geometry=np.full((len(rows),2,2),-10.,dtype=np.float32)
        geometry[valid,0,0]=pt[valid]%self.duration/self.duration
        geometry[valid,0,1]=pv[valid]
        geometry[valid,1,0]=t[rows[valid]]%self.duration/self.duration
        geometry[valid,1,1]=v[rows[valid]]
        self.positions[target]=geometry; self.stamps[target]=t[rows]
        self.values[target]=v[rows]; self.identities[target]=identities[newest]
        self.last_time=float(t[selected[-1]]); self.last_id=int(identities[-1])
        self._selected_time,self._selected_value=self.last_time,float(v[selected[-1]])
        stale=self.discard_before(self.last_time-self.duration-1e-9)
        changed=np.union1d(target,stale)
        return list(zip(changed.tolist(),self.positions[changed]))

    def discard_before(self, timestamp):
        """Clear occupied slots older than a sparse marker's visible sweep."""
        stale = np.flatnonzero(np.isfinite(self.stamps) & (self.stamps < timestamp))
        self.stamps[stale] = -np.inf
        self.values[stale] = np.nan
        self.identities[stale] = np.iinfo(np.int64).min
        self.positions[stale] = -10.
        return stale


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
        uniform float u_gain;
        uniform float u_center;
        varying vec4 v_color;
        void main() {
            vec2 position = vec2(a_position.x, u_center + u_gain * (a_position.y - u_center));
            gl_Position = $transform(vec4(position, 0., 1.));
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
            self.shared_program['u_gain'] = 1.0
            self.shared_program['u_center'] = 0.0
            self._draw_mode = mode
            self.set_gl_state('translucent', depth_test=False)

        def _prepare_transforms(self, view):
            view.view_program.vert['transform'] = view.transforms.get_transform()

        def _prepare_draw(self, view):
            return True

        def _compute_bounds(self, axis, view):
            return (0., 1.)

        def set_gain(self, gain, center):
            self.shared_program['u_gain'] = float(gain)
            self.shared_program['u_center'] = float(center)
            self.update()

        def reset_capacity(self, capacity):
            """Resize storage while retaining the linked shader program."""
            self.capacity = int(capacity)
            self._buffer.set_data(np.full(
                (self.capacity*self.vertices_per_slot, 2), -10., dtype=np.float32))
            self.update()

        def patch(self, updates, positions=None):
            if not updates:
                return
            # Merge consecutive ring slots into a single partial GPU write.
            slots = np.fromiter((slot for slot, _ in updates), dtype=np.intp)
            vertices = np.asarray([data for _, data in updates], dtype=np.float32)
            order = np.argsort(slots)
            slots, vertices = slots[order], vertices[order]
            boundaries = np.r_[0, np.flatnonzero(np.diff(slots) != 1) + 1, len(slots)]
            if positions is not None and len(boundaries)-1>8:
                # An extrema replay has irregular original sample slots. Avoid
                # hundreds of tiny driver commands per channel: upload the
                # existing geometry once, including unchanged/empty slots.
                # Copy because GL may consume the command after the ring mutates.
                self._buffer.set_subdata(positions.reshape(-1,2).copy(),offset=0)
                self.update()
                return
            for first, end in zip(boundaries[:-1], boundaries[1:]):
                data = vertices[first:end].reshape(-1, 2)
                self._buffer.set_subdata(
                    np.ascontiguousarray(data),
                    offset=int(slots[first])*self.vertices_per_slot)
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

    def set_gain(self, gain, center):
        self.visual.set_gain(gain, center)

    def reconfigure(self, duration, rate, max_gap=None):
        """Reset display history without replacing the GPU visual/program."""
        self.ring = SweepRing(duration, rate, max_gap)
        self.visual.reset_capacity(self.ring.capacity)

    def append(self, times, values, connect=None):
        updates = self.ring.append(times, values, connect)
        if self.mode == 'points':
            self.expire_points(self.ring.last_time)
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
        if self.mode == 'lines':
            self.visual.patch(updates,positions=self.ring.positions)
        else:
            self.visual.patch(updates)
        return len(updates)

    def expire_points(self, head):
        """Erase prior-cycle dots once the sweep has passed their timestamps.

        Measurements are sparse and jittered, so a new cycle may never write
        exactly the same 20 Hz slot as an old dot. Lines keep their existing
        partial-upload policy; only point slots are expired here.
        """
        if self.mode != 'points' or not np.isfinite(head):
            return 0
        stale = self.ring.discard_before(float(head) - self.ring.duration)
        self.visual.patch([(int(slot), np.array([[-10., -10.]], dtype=np.float32))
                           for slot in stale])
        return len(stale)

    def close(self):
        self.visual.parent = None
