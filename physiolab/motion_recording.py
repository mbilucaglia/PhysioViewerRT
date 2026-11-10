"""Recorded input-stage NLMS output and its portable provenance.

Saving the actual adaptive output preserves the learned state at capture time.
Replay starts from that stage, without rerunning or doubling adaptive cleaning.
The converted primary raw samples are retained separately for inspection/off.
"""
from copy import deepcopy
import numpy as np

MOTION_ALGORITHM = 'acc-nlms-v3-input'


def validate_static_calibration(value):
    if value is None:
        return
    try:
        zero, energy = value
        zero = np.asarray(zero, dtype=float)
        valid = (zero.shape == (3,) and np.isfinite(zero).all()
                 and np.linalg.norm(zero) > 1e-6
                 and np.isfinite(energy) and energy >= 0)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError('Invalid static ACC calibration')


def motion_configuration(value):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('algorithm') not in (
            'acc-nlms-v2-input', MOTION_ALGORITHM):
        raise ValueError('Unsupported recorded ACC cleaning configuration')
    indices = value.get('channels')
    if (not isinstance(indices, (list, tuple)) or len(indices) != 3
            or any(type(i) is not int or i < 0 for i in indices) or len(set(indices)) != 3
            or not isinstance(value.get('source_id'), str) or not value['source_id']
            or type(value.get('enabled')) is not bool or not value['enabled']
            or not isinstance(value.get('fs'), (int, float))
            or not np.isfinite(value['fs']) or value['fs'] <= 0):
        raise ValueError('Invalid recorded ACC cleaning configuration')
    validate_static_calibration(value.get('static_calibration'))
    threshold = value.get('intervention_threshold_mg', 5.)
    if (not isinstance(threshold, (int, float)) or not np.isfinite(threshold)
            or threshold <= 0):
        raise ValueError('Invalid recorded ACC intervention threshold')
    return deepcopy({**value, 'channels': list(indices)})


def recorded_input(item):
    """Choose raw or recorded post-NLMS samples, never silently bypass ACC."""
    raw = np.asarray(item['data'], dtype=float)
    config = motion_configuration(item.get('motion_reference'))
    if config is None:
        return raw
    cleaned = np.asarray(item.get('motion_cleaned'), dtype=float)
    if cleaned.shape != raw.shape or not np.isfinite(cleaned).all():
        raise ValueError('ACC calibration requires aligned finite post-NLMS samples; record it again')
    return cleaned
