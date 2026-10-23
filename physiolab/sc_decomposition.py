"""Rolling cvxEDA tonic conductance, shared by live and baseline processing.

The optimizer runs on the acquisition/processing thread, never the GUI thread.
cvxEDA (Luca Citi et al., GPL-3.0) is used without reimplementing its model:
https://github.com/lciti/cvxEDA
"""
from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import math
from threading import Lock

import numpy as np
from scipy.signal import resample_poly

_SOLVER_LOCK = Lock()  # cvxEDA temporarily changes cvxopt's global options.
MIN_MODEL_SAMPLES = 3  # cvxEDA's second-order ARMA model requires three samples.


def sc_pipeline_metadata(processor, preprocessing, conversion):
    """Identify both the numerical backend and the calibrated input transform."""
    from .source_conversion import SourceConversion
    metadata = {**processor.metadata(), 'preprocessing': dict(preprocessing),
                'conversion': dict(conversion or SourceConversion().metadata())}
    metadata['configuration_id'] = sha256(
        json.dumps(metadata, sort_keys=True).encode()).hexdigest()[:24]
    return metadata


@dataclass(frozen=True)
class SCDecompositionSettings:
    window_seconds: float = 20.
    hop_seconds: float = 1.
    edge_seconds: float = 0.
    analysis_hz: float = 8.
    tau0: float = 2.
    tau1: float = .7
    knot_seconds: float = 10.
    alpha: float = .0008
    gamma: float = .01
    gap_periods: float = 3.

    def __post_init__(self):
        if any(not math.isfinite(v) or (v < 0 if name == 'edge_seconds' else v <= 0)
               for name, v in asdict(self).items()):
            raise ValueError('SC decomposition settings must be finite and positive')
        if self.window_seconds <= self.edge_seconds * 2 + self.hop_seconds:
            raise ValueError('SC window must contain an interior aggregation interval')
        if self.analysis_hz < 2 or self.tau0 == self.tau1:
            raise ValueError('SC model requires >=2 Hz and distinct time constants')


@dataclass(frozen=True)
class TonicSCObservation:
    value: float
    timestamp: float
    window_start: float
    window_end: float
    available_time: float
    unit: str
    pipeline_id: str
    method: str = 'cvxEDA'


class TonicSCProcessor:
    """Bounded rolling adapter; inputs are already converted/filtered SC samples.

    The first channel is the configured SC channel. Each result averages one hop
    of tonic data through the newest sample. Processing begins on the first hop
    using available history, then grows to the bounded rolling window.
    """

    def __init__(self, settings=None, unit='a.u.'):
        self.settings = settings or SCDecompositionSettings()
        self.unit = str(unit or 'a.u.')
        try:
            import cvxeda
            self._backend = cvxeda.cvxEDA
            self._version = version('cvxeda')
        except (ImportError, PackageNotFoundError) as exc:
            self._backend = None
            self._version = 'unavailable'
            self._unavailable_reason = str(exc)
        identity = {'implementation': 2, 'library': 'cvxeda',
                    'version': self._version, 'settings': asdict(self.settings)}
        self.pipeline_id = 'cvxeda-' + sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
        self.reset()

    @property
    def available(self):
        return self._backend is not None

    def metadata(self):
        return {'method': 'cvxEDA', 'library_version': self._version,
                'pipeline_id': self.pipeline_id, 'settings': asdict(self.settings),
                'unit': self.unit, 'aggregation': 'trailing hop mean',
                'startup': 'first hop; progressively growing history',
                'nominal_delay_seconds': self.settings.edge_seconds + self.settings.hop_seconds / 2}

    def reset(self):
        self._values = np.empty(0)
        self._times = np.empty(0)
        self._fs = None
        self._next_end = None
        self.status = 'Waiting for SC decomposition history' if self.available else 'cvxEDA unavailable; install requirements-affect.txt'

    def push(self, samples, timestamps, fs):
        values = np.asarray(samples, dtype=float)
        if values.ndim == 2:
            values = values[:, 0]
        times = np.asarray(timestamps, dtype=float)
        if values.ndim != 1 or times.ndim != 1 or len(values) != len(times):
            raise ValueError('SC samples and timestamps must have equal one-dimensional lengths')
        if not math.isfinite(fs) or fs <= 0:
            raise ValueError('SC sampling rate must be finite and positive')
        if not self.available or not len(times):
            return []
        # Invalid samples break history rather than joining across a dropout.
        valid = np.isfinite(values) & np.isfinite(times)
        breaks = np.flatnonzero(~valid)
        if len(breaks):
            self.reset()
            start = int(breaks[-1]) + 1
            values, times = values[start:], times[start:]
            if not len(times):
                self.status = 'SC history reset after invalid samples'
                return []
        if self._fs is not None and not math.isclose(fs, self._fs, rel_tol=1e-6):
            self.reset()
        gaps = np.flatnonzero((np.diff(times) <= 0) | (np.diff(times) > self.settings.gap_periods / fs))
        if len(gaps):
            self.reset()
            start = int(gaps[-1]) + 1
            values, times = values[start:], times[start:]
        if len(self._times) and (times[0] <= self._times[-1] or times[0] - self._times[-1] > self.settings.gap_periods / fs):
            self.reset()
        self._fs = float(fs)
        if self._next_end is None:
            first_samples = max(math.ceil(fs*(self.settings.hop_seconds+self.settings.edge_seconds)),
                                math.ceil(MIN_MODEL_SAMPLES*fs/self.settings.analysis_hz))
            self._next_end = float(times[0] + (first_samples-1) / fs)
        self._values = np.concatenate((self._values, values))
        self._times = np.concatenate((self._times, times))
        observations = []
        tolerance = .25 / fs
        while self._times[-1] + tolerance >= self._next_end:
            end = self._next_end
            start = end - self.settings.window_seconds + 1 / fs
            mask = (self._times >= start - tolerance) & (self._times <= end + tolerance)
            try:
                observation = self._decompose(self._values[mask], self._times[mask], fs, end)
                observations.append(observation)
                self.status = 'Tonic SC ready (cvxEDA)'
            except Exception as exc:
                # Failure must not interrupt raw acquisition or other metrics.
                self.status = 'SC decomposition failed: ' + str(exc)
            self._next_end += self.settings.hop_seconds
        keep = self._times >= self._next_end - self.settings.window_seconds - 1 / fs
        self._values, self._times = self._values[keep], self._times[keep]
        return observations

    def _decompose(self, values, times, fs, end):
        ratio = Fraction(self.settings.analysis_hz / fs).limit_denominator(10000)
        reduced = resample_poly(values, ratio.numerator, ratio.denominator, padtype='line')
        effective_hz = fs * ratio.numerator / ratio.denominator
        if len(reduced) < MIN_MODEL_SAMPLES:
            raise ValueError('cvxEDA requires at least three analysis samples')
        reduced_times = times[0] + np.arange(len(reduced)) / effective_hz
        offset, scale = float(np.mean(reduced)), float(np.std(reduced))
        if scale <= np.finfo(float).eps * max(1., abs(offset)):
            tonic = np.full(len(reduced), offset)
        else:
            import cvxopt
            with _SOLVER_LOCK:
                previous_options = cvxopt.solvers.options.copy()
                try:
                    result = tuple(self._backend((reduced - offset) / scale, 1 / effective_hz,
                        tau0=self.settings.tau0, tau1=self.settings.tau1,
                        delta_knot=self.settings.knot_seconds, alpha=self.settings.alpha,
                        gamma=self.settings.gamma, options={'show_progress': False}))
                finally:
                    cvxopt.solvers.options.clear()
                    cvxopt.solvers.options.update(previous_options)
            tonic = np.asarray(result[2]) * scale + offset
        interval_end = float(end - self.settings.edge_seconds)
        interval_start = max(float(times[0]), interval_end - self.settings.hop_seconds)
        interior = (reduced_times > interval_start) & (reduced_times <= interval_end)
        if not interior.any() or not np.isfinite(tonic).all():
            raise ValueError('No finite interior tonic SC estimate')
        return TonicSCObservation(float(np.mean(tonic[interior])),
            (interval_start + interval_end) / 2, interval_start, interval_end,
            float(end), self.unit, self.pipeline_id)


def decompose_baseline(samples, timestamps, fs, settings=None, unit='a.u.'):
    """Produce the exact live rolling estimates for a recorded baseline.

    Callers apply the same source conversion and SC prefilter before this helper,
    and store metadata() with the baseline to reject incompatible old baselines.
    """
    processor = TonicSCProcessor(settings=settings, unit=unit)
    return processor.push(samples, timestamps, fs)
