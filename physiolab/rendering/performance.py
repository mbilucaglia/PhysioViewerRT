"""Opt-in, low-overhead runtime performance diagnostics.

Set PHYSIOLAB_PROFILE=1 before launching the app. Each JSON line is a
five-second summary; no raw signal data or participant information is logged.
"""
from collections import defaultdict
import json
import os
from pathlib import Path
import time


class PerformanceMonitor:
    def __init__(self, enabled=None, path=None, interval=5.0):
        self.enabled = (os.environ.get('PHYSIOLAB_PROFILE') == '1'
                        if enabled is None else enabled)
        self.path = Path(path) if path else Path.home() / 'PhysioViewerRT-performance.jsonl'
        self.interval = float(interval)
        self.last_flush = time.monotonic()
        self._samples = defaultdict(list)
        self._errors = 0

    def measure(self, name, seconds):
        if self.enabled:
            self._samples[name].append(round(float(seconds)*1000., 3))

    def maybe_flush(self, extras=None):
        if not self.enabled:
            return
        now = time.monotonic()
        if now - self.last_flush < self.interval:
            return
        report = {'monotonic': now}
        for key, samples in self._samples.items():
            if samples:
                report[key] = {
                    'count': len(samples),
                    'mean_ms': round(sum(samples) / len(samples), 3),
                    'worst_ms': max(samples)
                }
        report['queues'] = extras or {}
        try:
            with self.path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(report, default=str) + '\n')
        except OSError:
            self._errors += 1
            # Never let a diagnostics filesystem failure break recording.
            if self._errors >= 3:
                self.enabled = False
        self._samples.clear()
        self.last_flush = now
