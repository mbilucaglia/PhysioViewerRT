"""Source-time paired affect observations, independent of Qt and rendering.

The EDA input SCL is the canonical decomposed tonic metric; EI is independent.
References are nested modality/metric baseline summaries, as in calibration.py.
"""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import math

from .calibration import normalize


@dataclass(frozen=True)
class AffectPoint:
    at: float
    x: float
    y: float
    source_times: tuple[float, float]
    connected: bool = False


@dataclass(frozen=True)
class AffectResponse:
    key: str
    name: str
    color: str
    points: tuple[AffectPoint, ...]
    current: AffectPoint | None
    status: str


@dataclass(frozen=True)
class AffectSnapshot:
    responses: tuple[AffectResponse, ...]


@dataclass(frozen=True)
class _Pair:
    at: float
    x: float
    y: float
    source_times: tuple[float, float]
    connected: bool


# One owner for names, source bindings and presentation colors.
RESPONSE_DEFINITIONS = (
    ('central', 'Central response', '#138d90', ('EEG', 'AWI'), ('EEG', 'BAR')),
    ('peripheral', 'Peripheral response', '#8b5fc7', ('PPG', 'HR'), ('EDA', 'SCL')),
)
NORMALIZATION_MODES = ('zscore', 'zmad', 'robust_iqr', 'minmax')


def _finite(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class AffectState:
    """Bounded raw pairs reprojected with fixed references on snapshot().

    ``at`` and snapshot ``now`` must use the same source clock in seconds.
    max_age controls current-marker freshness; pair_tolerance limits HR/SCL skew.
    A delayed tonic observation selects the last HR at or before its source time.
    Rendering/fading/pause do not generate observations or alter these histories.
    """

    def __init__(self, max_age=2., pair_tolerance=1., max_points=1200,
                 history_seconds=300., peripheral_max_age=5.):
        for value in (max_age, pair_tolerance, history_seconds, peripheral_max_age):
            if _finite(value) is None or value <= 0:
                raise ValueError('Affect durations must be finite and positive')
        if isinstance(max_points, bool) or not isinstance(max_points, int) or max_points < 1:
            raise ValueError('Affect capacity must be a positive integer')
        self.max_age = float(max_age)
        self.peripheral_max_age = float(peripheral_max_age)
        self.pair_tolerance = float(pair_tolerance)
        self.history_seconds = float(history_seconds)
        self._history = {key: deque(maxlen=max_points) for key, *_ in RESPONSE_DEFINITIONS}
        self._hr = deque(maxlen=max_points)
        self._pending_tonic = None
        self._last_time = {}
        self._broken = {'central': True, 'peripheral': True}
        self._valid = {'central': False, 'peripheral': False}
        self._references = {}
        self._tonic_compatible = False

    def set_references(self, refs, tonic_compatible=True):
        """Use owned fixed summaries; caller verifies tonic pipeline provenance."""
        self._references = deepcopy(refs or {})
        self._tonic_compatible = bool(tonic_compatible)

    def clear(self):
        """Clear trails/current observations, retaining references and configuration."""
        self.reset()

    def reset(self, kind=None):
        """Clear the affected response on source/channel changes or stop."""
        if kind is not None and kind not in ('EEG', 'PPG', 'EDA'):
            return
        responses = ('central', 'peripheral') if kind is None else (
            ('central',) if kind == 'EEG' else ('peripheral',))
        for key in responses:
            self._history[key].clear()
            self._broken[key] = True
            self._valid[key] = False
        if kind is None:
            self._last_time.clear()
        else:
            self._last_time.pop(kind, None)
        if kind in (None, 'PPG', 'EDA'):
            self._hr.clear()
            self._pending_tonic = None

    def _invalidate(self, key):
        self._broken[key] = True
        self._valid[key] = False

    def _append(self, key, x, y, times):
        at = max(times)
        history = self._history[key]
        if history and at <= history[-1].at:
            return
        connected = (bool(history) and not self._broken[key]
                     and at - history[-1].at <= self._age_limit(key))
        history.append(_Pair(at, x, y, times, connected))
        self._broken[key] = False
        self._valid[key] = True
        while history and history[0].at < at - self.history_seconds:
            history.popleft()

    def _age_limit(self, key):
        return self.peripheral_max_age if key == 'peripheral' else self.max_age

    def update(self, kind, metric, at):
        """Consume an actual metric result; None means no new measurement.

        Duplicate/backward source timestamps are ignored independently per modality.
        Missing/nonfinite required values break their response without a fake point.
        """
        if kind not in ('EEG', 'PPG', 'EDA') or metric is None:
            return
        if kind == 'EEG' and metric.get('_partial') and not any(key in metric for key in ('AWI', 'BAR')):
            return  # Processing diagnostics are not missing EEG measurements.
        if kind == 'EDA':
            if 'SCL' not in metric:
                return
            at = metric.get('_tonic_at', at)
        at = _finite(at)
        if at is None or at <= self._last_time.get(kind, -math.inf):
            return
        self._last_time[kind] = at
        if kind == 'EEG':
            x, y = _finite(metric.get('AWI')), _finite(metric.get('BAR'))
            if x is None or y is None:
                self._invalidate('central')
            else:
                self._append('central', x, y, (at, at))
            return
        if kind == 'PPG':
            hr = _finite(metric.get('HR'))
            if hr is None:
                self._hr.clear()
                self._pending_tonic = None
                self._invalidate('peripheral')
                return
            self._hr.append((at, hr))
            while self._hr and self._hr[0][0] < at - self.history_seconds:
                self._hr.popleft()
        else:
            # Ordinary EDA updates without a decomposition result are not tonic
            # failures: asynchronous decomposition publishes SCL separately.
            if 'SCL' not in metric:
                return
            tonic = _finite(metric['SCL'])
            if tonic is None:
                self._pending_tonic = None
                self._invalidate('peripheral')
                return
            self._pending_tonic = (at, tonic)
        self._pair_peripheral()

    def _pair_peripheral(self):
        if self._pending_tonic is None:
            return
        tonic_at, tonic = self._pending_tonic
        candidate = next(((at, hr) for at, hr in reversed(self._hr)
                          if at <= tonic_at), None)
        if candidate is None or tonic_at - candidate[0] > self.pair_tolerance:
            self._invalidate('peripheral')
            return
        self._append('peripheral', candidate[1], tonic, (candidate[0], tonic_at))
        self._pending_tonic = None

    def _normalized(self, value, binding, mode):
        kind, name = binding
        reference = self._references.get(kind, {}).get(name)
        if not reference:
            return None
        try:
            return _finite(normalize(value, reference, mode))
        except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
            return None

    def snapshot(self, now, retention, normalization='zscore'):
        """Return immutable normalized geometry and independent marker/status data.

        points contain retained observations only; connected=False starts a trail.
        No current marker is returned after max_age, invalid input or missing refs.
        Identity cannot compare these unlike physical measures on shared axes.
        """
        if _finite(now) is None or _finite(retention) is None or retention <= 0:
            raise ValueError('Snapshot time and positive retention must be finite')
        if normalization not in (*NORMALIZATION_MODES, 'identity'):
            raise ValueError('Unknown affect normalization mode')
        responses = []
        for key, name, color, x_binding, y_binding in RESPONSE_DEFINITIONS:
            points = []
            status = 'Waiting for valid metric observations'
            available = True
            if normalization == 'identity':
                status, available = 'Select baseline normalization for shared affect axes', False
            elif key == 'peripheral' and not self._tonic_compatible:
                status, available = 'Matching decomposed tonic SCL baseline required', False
            else:
                for binding in (x_binding, y_binding):
                    if self._normalized(0., binding, normalization) is None:
                        status, available = 'Valid baseline references required', False
                        break
            if available:
                previous_valid = False
                for pair in self._history[key]:
                    if not now - min(retention, self.history_seconds) <= pair.at <= now:
                        continue
                    x = self._normalized(pair.x, x_binding, normalization)
                    y = self._normalized(pair.y, y_binding, normalization)
                    if x is None or y is None:
                        previous_valid = False
                        continue
                    points.append(AffectPoint(pair.at, x, y, pair.source_times,
                                              pair.connected and previous_valid))
                    previous_valid = True
                status = 'Live' if points and self._valid[key] else status
            current = None
            if points and self._valid[key]:
                age = now - min(points[-1].source_times)
                if age <= self._age_limit(key):
                    current = points[-1]
                else:
                    status = 'Stale metric observations'
            responses.append(AffectResponse(key, name, color, tuple(points), current, status))
        return AffectSnapshot(tuple(responses))
