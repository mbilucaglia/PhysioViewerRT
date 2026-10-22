"""Raw display session state, independent of widgets and GPU resources.

This is the single owner of retained samples, presentation time, scale
references and the latest-only frame lifecycle. GUI code supplies view choices
and presents accepted frames; acquisition and processing never depend on it.
"""
from collections import deque
import time

import numpy as np

from .display_units import DEFAULT_EEG_DISPLAY_STEP, ARBITRARY_UNIT
from .raw_timing import clean_lsl_chunk, SmoothViewportClock
from .render_contracts import RawFrameRequest
from .settings import DEFAULT_VIEWER_SETTINGS


class RawDisplayState:
    def __init__(self, settings=DEFAULT_VIEWER_SETTINGS, modalities=('EEG', 'EDA', 'PPG')):
        self.settings = settings
        self.history = {kind: deque() for kind in modalities}
        self.bounds = (-settings.default_view_seconds, 0.)
        self.view_seconds = settings.default_view_seconds
        self.follow_live = True
        self.paused = False
        self.origin = self.latest_time = self.last_received_at = None
        self.last_sample = {}
        self.clock = SmoothViewportClock(settings.presentation_delay_seconds)
        self.committed_head = None
        self.references = {}
        self.display_scales = {'EEG': DEFAULT_EEG_DISPLAY_STEP}
        self.units = dict.fromkeys(modalities, ARBITRARY_UNIT)
        self.frames = {}
        self.autoscale_requests = set()
        self.dirty = True
        self.epoch = self.ticket = 0
        self.inflight_ticket = None
        self.last_render_at = self.interacting_until = 0.
        self.tab_entered_at = None

    def invalidate(self):
        self.epoch += 1
        self.dirty = True

    def set_window(self, seconds):
        self.view_seconds = float(seconds)
        self.invalidate()

    def set_units(self, kind, scales, unit):
        self.display_scales[kind] = scales
        self.units[kind] = unit
        self.references.pop(kind, None)
        self.invalidate()

    def reset(self, kind):
        self.frames.pop(kind, None)
        self.autoscale_requests.discard(kind)
        self.history[kind].clear()
        self.last_sample.pop(kind, None)
        self.references.pop(kind, None)
        if not self.last_sample:
            self.clock.reset()
            self.committed_head = None
            self.origin = self.latest_time = self.last_received_at = None
        self.invalidate()

    def append(self, kind, raw, filtered, names, fs, timestamps, received_at=None):
        t, raw, filtered = clean_lsl_chunk(timestamps, raw, filtered,
                                         self.last_sample.get(kind))
        if not len(t):
            return
        self.last_sample[kind] = float(t[-1])
        if self.origin is None:
            self.origin = float(t[0])
        self.history[kind].append((t, raw.copy(), filtered.copy(), list(names), float(fs)))
        if self.latest_time is None or float(t[-1]) > self.latest_time:
            self.latest_time = float(t[-1])
            self.last_received_at = time.monotonic() if received_at is None else received_at
            self.clock.observe(self.latest_time, self.last_received_at)
        cutoff = self.latest_time-self.settings.history_seconds
        chunks = self.history[kind]
        while chunks and chunks[0][0][-1] < cutoff:
            chunks.popleft()
        self.dirty = True

    def advance(self, now):
        head = self.clock.advance(now)
        # Acquisition time continues while a tab is hidden or plotting paused.
        # Only the viewport freezes; resuming must not slew through old time.
        if head is None or self.origin is None or not self.follow_live or self.paused:
            return False
        if self.last_sample:
            newest = max(self.last_sample.values())
            fresh = [stamp for stamp in self.last_sample.values()
                     if newest-stamp <= self.settings.stale_source_seconds]
            head = min(head, min(fresh))
        end = head-self.origin
        if self.committed_head is not None:
            end = max(end, self.committed_head)
        bounds = (end-self.view_seconds, end)
        changed = bounds != self.bounds
        self.bounds = bounds
        return changed

    def request_autoscale(self, kind):
        if kind in self.frames:
            self.autoscale_requests.add(kind)
            self.invalidate()

    def begin_frame(self, sources, queued_at=None):
        if not sources or self.inflight_ticket is not None:
            return None
        self.ticket += 1
        self.inflight_ticket = self.ticket
        return RawFrameRequest(self.ticket, self.epoch, sources,
                               time.perf_counter() if queued_at is None else queued_at,
                               self.bounds[1])

    def accepts(self, ticket, version):
        if ticket != self.inflight_ticket:
            return False
        self.inflight_ticket = None
        return version == self.epoch

    def remember_frame(self, kind, frame):
        """Return whether retained GPU geometry needs a scale replay."""
        previous = self.references.get(kind)
        centers, scales = frame[3:5]
        changed = (previous is not None
                   and (not np.array_equal(previous[0], centers)
                        or not np.array_equal(previous[1], scales)))
        self.frames[kind] = frame
        self.references[kind] = (centers, scales)
        return changed
