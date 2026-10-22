"""Metric observations and derived EI state, independent of widgets and plots."""
from collections import deque

import numpy as np

from .calibration import normalize
from .emotion import BaselineEmotionalIndex
from .metric_catalog import validate_metrics


class MetricState:
    def __init__(self, definitions, history_capacity=900):
        self.definitions = validate_metrics(definitions)
        self.keys = [definition.key for definition in self.definitions]
        self.latest = {}
        self.history = {key: deque(maxlen=history_capacity) for key in self.keys}
        self.ei = BaselineEmotionalIndex()

    def update(self, kind, metric, at):
        if metric is None:
            return
        at = float(at)
        self.latest[kind] = metric
        for modality, name in self.keys:
            if modality == kind:
                value = metric.get(name)
                value = (float(value) if isinstance(value, (int, float))
                         and np.isfinite(value) else float('nan'))
                self.history[modality, name].append((at, value))
        if kind in ('PPG', 'EDA'):
            name = 'HR' if kind == 'PPG' else 'SCL'
            self.ei.update(kind, metric.get(name), at)
            value = self.ei.value(at)
            self.latest['EI'] = {
                'EI': value,
                'status': ('EI from HR/GSR z-scores against BSL' if value is not None
                           else 'EI needs valid BSL HR/SCL references and fresh signals'),
            }
            if ('EI', 'EI') in self.history:
                self.history['EI', 'EI'].append(
                    (at, float(value) if value is not None else float('nan')))

    def reset(self, kind):
        self.latest.pop(kind, None)
        for key in self.keys:
            if key[0] == kind:
                self.history[key].clear()
        if kind in ('EDA', 'PPG'):
            self.ei.latest.clear()
            self.latest.pop('EI', None)
            if ('EI', 'EI') in self.history:
                self.history['EI', 'EI'].clear()

    @staticmethod
    def normalized_value(kind, name, value, mode, references):
        if value is None or not isinstance(value, (int, float)) or not np.isfinite(value):
            return None
        if mode == 'identity' or (kind == 'EEG' and name == 'IAF'):
            return float(value)
        reference = (references or {}).get(kind, {}).get(name)
        if reference is None:
            return None
        return normalize(value, reference, mode)
