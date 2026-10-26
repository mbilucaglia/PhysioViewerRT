"""Bounded, thread-safe clean-window accumulation before ASR reconstruction.

Quality is a conservative screening heuristic, not an artifact-free guarantee.
Unit-independent checks use 1-second windows and an adaptive median RMS of
previous accepted windows. Original source timestamps are retained per window.
"""
from collections import deque
from threading import Lock
import time
import numpy as np


class ASRTrainingAccumulator:
    def __init__(self, fs, channels, maximum_seconds=180.):
        self.fs, self.channels = float(fs), tuple(channels)
        self.window = round(fs)
        self.maximum_samples = round(maximum_seconds*fs)
        self.lock = Lock()
        self.pending = None
        self.accepted = []
        self.reference = deque(maxlen=30)
        self.accepted_samples = self.rejected_samples = self.seen_samples = 0
        self.windows_seen = 0
        self.last_arrival = None
        self.last_source = None
        self.state, self.reason = 'warming', 'Checking signal… relax and keep still.'

    def push(self, raw, filtered, timestamps, now=None):
        raw, filtered, stamps = np.asarray(raw), np.asarray(filtered), np.asarray(timestamps)
        if not len(stamps):
            return
        with self.lock:
            self.last_arrival = time.monotonic() if now is None else float(now)
            self.seen_samples += len(stamps)
            if (raw.shape != filtered.shape or raw.shape != (len(stamps), len(self.channels))
                    or not np.isfinite(raw).all() or not np.isfinite(filtered).all()
                    or not np.isfinite(stamps).all()):
                self.state, self.reason = 'bad', 'Check signal/electrodes: invalid EEG samples.'
                self.rejected_samples += len(stamps)+(len(self.pending[2]) if self.pending is not None else 0)
                self.pending = None
                return
            gap = max(.25, 3/self.fs)
            if (np.any(np.diff(stamps) <= 0) or np.any(np.diff(stamps) > gap)
                    or (self.last_source is not None and
                        not 0 < stamps[0]-self.last_source <= gap)):
                self.last_source = float(stamps[-1])
                self.rejected_samples += len(stamps)+(len(self.pending[2]) if self.pending is not None else 0)
                self.pending = None
                self.state, self.reason = 'bad', 'Signal interrupted—check the EEG connection.'
                return
            self.last_source = float(stamps[-1])
            if self.pending is not None:
                raw = np.concatenate((self.pending[0], raw))
                filtered = np.concatenate((self.pending[1], filtered))
                stamps = np.concatenate((self.pending[2], stamps))
            start = 0
            while len(stamps)-start >= self.window:
                stop = start+self.window
                x, y, t = raw[start:stop], filtered[start:stop], stamps[start:stop]
                self.windows_seen += 1
                centered = y-y.mean(axis=0)
                rms = np.sqrt(np.mean(centered**2, axis=0))
                scale = max(float(np.median(rms)), np.finfo(float).tiny)
                flat = (np.ptp(x, axis=0) == 0) | (rms <= scale*1e-8)
                plateau = np.maximum((x == x.max(axis=0)).sum(axis=0),
                                     (x == x.min(axis=0)).sum(axis=0)) > max(3, .1*self.window)
                if np.any(flat) or np.any(plateau):
                    indices = np.flatnonzero(flat | plateau)
                    names = ', '.join(self.channels[i] for i in indices[:4])
                    self.state, self.reason = 'bad', f'Check signal/electrodes: flat or clipped {names}.'
                elif np.linalg.matrix_rank(centered) < len(self.channels):
                    self.state, self.reason = 'bad', 'Check electrodes: duplicated/dependent channel signals.'
                elif self.windows_seen <= 2:
                    self.reference.append(rms)
                    self.state, self.reason = 'warming', 'Learning signal level… relax and keep still.'
                else:
                    baseline = np.median(np.asarray(self.reference), axis=0) if self.reference else rms
                    burst = np.any(rms > np.maximum(baseline, scale*1e-8)*6.)
                    peak = np.max(np.abs(centered), axis=0)/np.maximum(rms, scale*1e-8)
                    if burst or np.any(peak > 8.):
                        self.state, self.reason = 'movement', 'Possible movement—relax and keep still.'
                    else:
                        self.state, self.reason = 'good', 'Signal looks stable—keep still.'
                        self.reference.append(rms)
                        if self.accepted_samples+self.window <= self.maximum_samples:
                            self.accepted.append((x.copy(), y.copy(), t.copy()))
                            self.accepted_samples += self.window
                if self.state != 'good':
                    self.rejected_samples += self.window
                start = stop
            self.pending = (raw[start:].copy(), filtered[start:].copy(), stamps[start:].copy())

    def status(self, now=None):
        with self.lock:
            state, reason = self.state, self.reason
            clock = time.monotonic() if now is None else now
            if self.last_arrival is None:
                state, reason = 'warming', 'Waiting for EEG… relax and keep still.'
            elif clock-self.last_arrival > 1.:
                state, reason = 'bad', 'No fresh EEG—check the connection.'
            return {'state': state, 'reason': reason,
                'accepted_seconds': self.accepted_samples/self.fs,
                'rejected_seconds': self.rejected_samples/self.fs,
                'recorded_seconds': self.seen_samples/self.fs}

    def snapshot(self, metadata):
        with self.lock:
            if not self.accepted:
                raise ValueError('No usable EEG windows collected yet')
            return {**metadata, 'data': np.concatenate([w[0] for w in self.accepted]),
                'preprocessed_data': np.concatenate([w[1] for w in self.accepted]),
                'timestamps': np.concatenate([w[2] for w in self.accepted]),
                'accepted_window_samples': [len(w[2]) for w in self.accepted]}
