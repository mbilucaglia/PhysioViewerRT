"""Validate stored calibration recordings before analysis or activation."""
import math
from numbers import Real

import numpy as np

DURATION_SECONDS = 60.0


def validate_calibration(meta, streams, expected_kind):
    """Reject incoherent samples; preserve optional schema-1 legacy metadata.

    Timestamps must be strictly increasing. We never sort, interpolate or repair
    a recording, because doing so would silently change the acquired signal.
    Saved analysis is not trusted as live state: the application recalculates it.
    """
    if (expected_kind not in ('EYC', 'BSL') or not isinstance(meta, dict)
            or meta.get('schema') not in (1, 2) or meta.get('type') != expected_kind):
        raise ValueError('Unexpected calibration type/schema')
    descriptors = meta.get('streams')
    if not isinstance(descriptors, dict) or not descriptors:
        raise ValueError('Calibration streams are missing')
    if expected_kind == 'EYC' and 'EEG' not in descriptors:
        raise ValueError('EYC EEG stream missing')
    for kind, descriptor in descriptors.items():
        if kind not in ('EEG', 'EDA', 'PPG') or not isinstance(descriptor, dict):
            raise ValueError(f'Invalid stream descriptor: {kind}')
        if kind not in streams:
            raise ValueError(f'Missing signal arrays for {kind}')
        fs, channels = descriptor.get('fs'), descriptor.get('channels')
        if isinstance(fs, bool) or not isinstance(fs, Real) or not math.isfinite(fs) or fs <= 0:
            raise ValueError(f'{kind}: sampling frequency must be finite and positive')
        if (not isinstance(channels, list) or not channels
                or any(not isinstance(name, str) or not name.strip() for name in channels)):
            raise ValueError(f'{kind}: channel labels must be nonempty strings')
        data, timestamps = streams[kind]['data'], streams[kind]['timestamps']
        if descriptor.get('motion_reference') is not None:
            if meta['schema'] != 2:
                raise ValueError('ACC calibration requires schema 2')
            from .motion_recording import recorded_input
            recorded_input({**streams[kind], 'motion_reference': descriptor['motion_reference']})
        if (data.ndim != 2 or not len(data) or data.shape[1] != len(channels)
                or timestamps.ndim != 1 or len(timestamps) != len(data)):
            raise ValueError(f'{kind}: invalid file signal dimensions')
        if not np.isfinite(data).all() or not np.isfinite(timestamps).all():
            raise ValueError(f'{kind}: samples and timestamps must be finite')
        if np.any(np.diff(timestamps) <= 0):
            raise ValueError(f'{kind}: timestamps must be strictly increasing')
        if 'samples' in descriptor and descriptor['samples'] != len(data):
            raise ValueError(f'{kind}: sample count differs from stored data')
        for key in ('units', 'source_units'):
            units = descriptor.get(key, [])
            if (not isinstance(units, list) or (units and len(units) != len(channels))
                    or any(not isinstance(unit, str) for unit in units)):
                raise ValueError(f'{kind}: invalid {key}')
        for key in ('preprocessing', 'conversion'):
            if not isinstance(descriptor.get(key, {}), dict):
                raise ValueError(f'{kind}: invalid {key}')
