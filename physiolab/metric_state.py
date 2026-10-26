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
        self._definitions = {definition.key: definition for definition in self.definitions}
        self.latest = {}
        self.history = {key: deque(maxlen=history_capacity) for key in self.keys}
        self.observations = {key: deque(maxlen=history_capacity) for key in self.keys}
        self.ei = BaselineEmotionalIndex()

    def update(self, kind, metric, at):
        if metric is None:
            return
        at = float(at)
        previous = self.latest.get(kind, {})
        asynchronous_only = bool(metric.get('_partial')) or (any(
            item.modality == kind and item.asynchronous and item.name in metric
            for item in self.definitions) and not any(
            item.modality == kind and not item.asynchronous and item.name in metric
            for item in self.definitions))
        retained = {item.name: previous[item.name] for item in self.definitions
                    if item.modality == kind and item.asynchronous
                    and item.name in previous}
        # Large sample telemetry belongs to acquisition, never retained metric state.
        fields = {key: value for key, value in metric.items() if not isinstance(value, np.ndarray)}
        self.latest[kind] = {**(previous if asynchronous_only else retained), **fields}
        for modality, name in self.keys:
            if modality == kind:
                definition = self._definitions[modality, name]
                if (definition.asynchronous or asynchronous_only) and name not in metric:
                    continue
                value = metric.get(name)
                value = (float(value) if isinstance(value, (int, float))
                         and np.isfinite(value) else float('nan'))
                self.history[modality, name].append((at, value))
                provenance = metric.get('_observations', {}).get(name)
                if provenance is not None:
                    self.observations[modality, name].append(provenance)
        name = {'PPG': 'HR', 'EDA': 'SCL'}.get(kind)
        if name is not None and name in metric:
            provenance = metric.get('_observations', {}).get(name, {})
            source_at = float(provenance.get('window_end', metric.get('_tonic_at', at)))
            self.ei.update(kind, metric[name], source_at)
            value = self.ei.value()
            self.latest['EI'] = {
                'EI': value,
                'status': ('EI from HR/tonic SCL z-scores against BSL' if value is not None
                           else self.ei_unavailable_reason()),
            }
            if ('EI', 'EI') in self.history:
                self.history['EI', 'EI'].append(
                    (at, float(value) if value is not None else float('nan')))

    def ei_unavailable_reason(self):
        problem = self.ei.reference_problem()
        if problem:
            return problem
        if 'HR' not in self.ei.latest:
            return 'EI needs a valid HR measurement'
        if 'SCL' not in self.ei.latest:
            return 'EI needs a cvxEDA tonic SCL measurement'
        return 'EI needs valid HR and tonic SCL measurements'

    def set_ei_references(self, hr, scl):
        # A new baseline/pipeline must never reuse observations from the old one.
        if self.ei.hr_reference == hr and self.ei.scl_reference == scl:
            return
        self.ei.set_references(hr, scl)
        self.ei.latest.clear()
        self.latest.pop('EI', None)
        self.history.get(('EI', 'EI'), []).clear()

    def reset(self, kind):
        self.latest.pop(kind, None)
        for key in self.keys:
            if key[0] == kind:
                self.history[key].clear()
                self.observations[key].clear()
        if kind in ('EDA', 'PPG'):
            self.ei.latest.clear()
            self.latest.pop('EI', None)
            if ('EI', 'EI') in self.history:
                self.history['EI', 'EI'].clear()

    @staticmethod
    def normalized_value(kind, name, value, mode, references):
        if value is None or not isinstance(value, (int, float)) or not np.isfinite(value):
            return None
        if kind == 'EI':
            reference = (references or {}).get('EI', {}).get('EI')
            if not reference or not all(np.isfinite(reference.get(k, np.nan)) for k in ('mu', 'sigma')):
                return None
            return normalize(value, reference, 'zscore')
        if mode == 'identity' or (kind == 'EEG' and name == 'IAF'):
            return float(value)
        reference = (references or {}).get(kind, {}).get(name)
        if reference is None:
            return None
        return normalize(value, reference, mode)
