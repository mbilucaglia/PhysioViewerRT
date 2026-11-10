"""Calibration sample capture state with no Qt, dialogs, or filesystem access."""
from dataclasses import dataclass, field
from copy import deepcopy

import numpy as np

from .calibration import samples_after_timestamp


@dataclass
class CalibrationSession:
    kind: str
    streams: dict
    deadline: float
    errors: list[str] = field(default_factory=list)

    def __post_init__(self):
        # Own the capture lists and metadata rather than mutating the caller's
        # receiver metadata while the modal recording window runs.
        self.streams = {
            kind: {**metadata, 'channels': list(metadata['channels']),
                   'preprocessing': dict(metadata.get('preprocessing', {})),
                   'conversion': dict(metadata.get('conversion', {})),
                   'source_units': list(metadata.get('source_units', [])),
                   'units': list(metadata.get('units', [])),
                   'chunks': list(metadata.get('chunks', [])),
                   'motion_reference': deepcopy(metadata.get('motion_reference')),
                   'motion_chunks': [],
                   'times': list(metadata.get('times', []))}
            for kind, metadata in self.streams.items()
        }

    def append(self, kind, samples, timestamps, names, fs, now, motion_cleaned=None):
        if kind not in self.streams or now > self.deadline:
            return
        arr = np.asarray(samples, dtype=float)
        ts = np.asarray(timestamps, dtype=float)
        if arr.ndim != 2 or ts.ndim != 1 or len(arr) != len(ts) or not len(ts):
            return
        item = self.streams[kind]
        motion = None
        if item.get('motion_reference') is not None:
            motion = np.asarray(motion_cleaned, dtype=float)
            if motion.shape != arr.shape or not np.isfinite(motion).all():
                self.errors.append(f'{kind}: missing or invalid post-NLMS samples')
                return
            motion, _ = samples_after_timestamp(motion, ts, item.get('start_lsl_timestamp'))
        if (item['channels'] != list(names) or item['fs'] != float(fs)
                or arr.shape[1] != len(item['channels'])):
            self.errors.append(f'{kind} stream metadata changed')
            return
        arr, ts = samples_after_timestamp(arr, ts, item.get('start_lsl_timestamp'))
        if len(ts):
            item['chunks'].append(arr.copy())
            item['times'].append(ts.copy())
            if motion is not None:
                item['motion_chunks'].append(motion.copy())

    def recorded_seconds(self, kind):
        item = self.streams.get(kind)
        return sum(len(chunk) for chunk in item['chunks'])/item['fs'] if item else 0.

    def finish(self, minimum_seconds=55.):
        if self.errors:
            raise ValueError('\n'.join(self.errors))
        if not self.streams:
            raise ValueError('Calibration has no expected streams')
        streams = {}
        for kind, item in self.streams.items():
            if not item['chunks']:
                raise ValueError(f'{kind}: no samples recorded. Please retry.')
            data = np.concatenate(item['chunks'])
            timestamps = np.concatenate(item['times'])
            duration = len(data) / item['fs']
            if duration < minimum_seconds:
                raise ValueError(f'{kind}: only {duration:.1f} s of samples. Please retry.')
            streams[kind] = {
                'data': data, 'timestamps': timestamps,
                'fs': item['fs'], 'channels': list(item['channels']),
                'preprocessing': dict(item['preprocessing']),
                'conversion': dict(item['conversion']),
                'source_units': list(item['source_units']),
                'units': list(item['units']),
            }
            if item.get('motion_reference') is not None:
                streams[kind]['motion_reference'] = deepcopy(item['motion_reference'])
                streams[kind]['motion_cleaned'] = np.concatenate(item['motion_chunks'])
        return streams
