"""Stateful EEG ASR adapter using meegkit's BSD-licensed public implementation.

https://github.com/nbara/python-meegkit
Inputs are converted and high-pass filtered by the application's existing stage.
No EEG filtering or reconstruction mathematics is reimplemented here.
"""
from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib.metadata import version
import json
import math

import numpy as np


class ASRError(ValueError):
    """Unavailable backend, incompatible model, or unsuitable calibration."""


def _backend():
    try:
        from meegkit.asr import ASR
        return ASR
    except (ImportError, OSError) as exc:
        raise ASRError('ASR backend unavailable; install requirements-asr.txt') from exc


@dataclass(frozen=True)

class ASRSettings:
    cutoff: float = 20.
    window_seconds: float = .5
    step_seconds: float = .125
    maxdims: float = .66
    minimum_baseline_seconds: float = 30.

    def __post_init__(self):
        if any(not math.isfinite(v) or v <= 0 for v in asdict(self).values()):
            raise ASRError('ASR settings must be finite and positive')
        if self.cutoff < 2.5 or self.step_seconds > self.window_seconds:
            raise ASRError('ASR cutoff must be >=2.5 and step must fit the window')
        if self.maxdims != .66:
            raise ASRError('meegkit currently supports only maxdims=0.66')
        if self.minimum_baseline_seconds < 30:
            raise ASRError('ASR calibration requires at least 30 seconds')


def _validated_data(data, channel_count):
    result = np.asarray(data, dtype=float)
    if result.ndim != 2 or result.shape[1] != channel_count:
        raise ASRError('ASR expects samples by the original ordered EEG channels')
    if not np.isfinite(result).all():
        raise ASRError('ASR input contains nonfinite samples')
    return result


@dataclass(frozen=True)

class ASRModel:
    sampling_rate: float
    channels: tuple
    source_configuration: dict
    settings: ASRSettings
    M: np.ndarray
    T: np.ndarray
    A: np.ndarray
    B: np.ndarray
    baseline_seconds: float
    clean_seconds: float
    backend_version: str
    input_scale: float = 1.

    def __post_init__(self):
        if not math.isfinite(self.input_scale) or self.input_scale <= 0:
            raise ASRError('ASR input scale must be finite and positive')
        if not math.isfinite(self.sampling_rate) or self.sampling_rate <= 82:
            raise ASRError('ASR spectral shaping requires an EEG sampling rate above 82 Hz')
        channels = tuple(str(c) for c in self.channels)
        if len(channels) < 2 or len(set(channels)) != len(channels):
            raise ASRError('ASR requires at least two distinct EEG channel names')
        object.__setattr__(self, 'channels', channels)
        # JSON round-trip also rejects unsafe/nonportable configuration objects.
        config = json.loads(json.dumps(self.source_configuration, sort_keys=True, allow_nan=False))
        object.__setattr__(self, 'source_configuration', config)
        n = len(channels)
        for field in ('M', 'T', 'A', 'B'):
            array = np.array(getattr(self, field), dtype=float, copy=True)
            if not np.isfinite(array).all():
                raise ASRError('ASR model contains nonfinite coefficients')
            if field in ('M', 'T') and array.shape != (n, n):
                raise ASRError('ASR model matrices do not match EEG channels')
            if field in ('A', 'B') and (array.ndim != 1 or len(array) != 9):
                raise ASRError('ASR model needs order-eight spectral filter coefficients')
            array.setflags(write=False)
            object.__setattr__(self, field, array)
        if np.linalg.matrix_rank(self.M) != n or np.linalg.matrix_rank(self.T) != n:
            raise ASRError('ASR model matrices are rank deficient')
        if self.A[0] == 0:
            raise ASRError('ASR spectral filter denominator is invalid')
        if not all(math.isfinite(v) and v >= 30 for v in (self.baseline_seconds, self.clean_seconds)):
            raise ASRError('ASR model requires at least 30 seconds of retained calibration')

    @property

    def fs(self):
        return self.sampling_rate

    @property

    def model_id(self):
        encoded = json.dumps(self.to_dict(include_id=False), sort_keys=True, separators=(',', ':'), allow_nan=False)
        return 'asr-' + sha256(encoded.encode()).hexdigest()[:20]

    def to_dict(self, include_id=True):
        result = {'schema': 1, 'backend': 'meegkit', 'backend_version': self.backend_version,
                  'sampling_rate': self.sampling_rate, 'channels': list(self.channels),
                  'source_configuration': json.loads(json.dumps(self.source_configuration)),
                  'settings': asdict(self.settings), 'baseline_seconds': self.baseline_seconds,
                  'clean_seconds': self.clean_seconds, 'input_scale': self.input_scale,
                  **{field: getattr(self, field).tolist() for field in ('M', 'T', 'A', 'B')}}
        if include_id:
            result['model_id'] = self.model_id
        return result

    @classmethod

    def from_dict(cls, data):
        if data.get('schema') != 1 or data.get('backend') != 'meegkit':
            raise ASRError('Unsupported ASR calibration format')
        try:
            result = cls(float(data['sampling_rate']), tuple(data['channels']),
                         data['source_configuration'], ASRSettings(**data['settings']),
                         *(data[field] for field in ('M', 'T', 'A', 'B')),
                         float(data['baseline_seconds']), float(data['clean_seconds']),
                         str(data['backend_version']), float(data.get('input_scale', 1.)))
        except (KeyError, TypeError) as exc:
            raise ASRError('Invalid ASR calibration metadata') from exc
        if 'model_id' in data and data['model_id'] != result.model_id:
            raise ASRError('ASR calibration fingerprint does not match its coefficients')
        return result

    def metadata(self):
        return {key: value for key, value in self.to_dict().items() if key not in ('M', 'T', 'A', 'B')}


def fit_asr(baseline, fs, channels, source_config, settings=None):
    """Fit on a reasonably clean, converted, prefiltered training recording on a worker thread."""
    settings = settings or ASRSettings()
    channels = tuple(str(c) for c in channels)
    if len(channels) < 2 or len(set(channels)) != len(channels):
        raise ASRError('ASR requires at least two distinct EEG channels')
    if not math.isfinite(fs) or fs <= 82:
        raise ASRError('ASR spectral shaping requires an EEG sampling rate above 82 Hz')
    data = _validated_data(baseline, len(channels))
    if len(data) / fs < settings.minimum_baseline_seconds:
        raise ASRError('Record at least 30 seconds of EEG training data before fitting ASR')
    centered = data - np.mean(data, axis=0)
    if np.linalg.matrix_rank(centered) < len(channels):
        raise ASRError('EEG training data has flat or linearly dependent channels; check electrodes and record clean training data; channels will not be removed')
    backend = _backend()(sfreq=fs, cutoff=settings.cutoff, win_len=settings.window_seconds, method='euclid')
    try:
        # The library's geometric median has an absolute convergence tolerance.
        # Normalize once from training so volts and microvolts have identical numerical
        # conditioning; keep that fixed scale for all subsequent live samples.
        input_scale = 1. / float(np.sqrt(np.mean(centered ** 2)))
        clean, _ = backend.fit(data.T.copy() * input_scale)
        if clean.shape[-1] / fs < settings.minimum_baseline_seconds:
            raise ASRError('ASR retained less than 30 seconds of clean EEG training data; record a cleaner/longer training recording')
        return ASRModel(float(fs), channels, source_config, settings,
                        backend.state_['M'], backend.state_['T'], *backend.ab_,
                        len(data) / fs, clean.shape[-1] / fs, version('meegkit'), input_scale)
    except ASRError:
        raise
    except Exception as exc:
        raise ASRError('ASR calibration failed: ' + str(exc)) from exc


class StreamingASR:
    """Persistent backend states; zero added lookahead and unchanged sample count.

    meegkit has chunk-dependent covariance/cosine transitions. Chunks are
    bounded to step_seconds here, but different transport partitions are not
    mathematically identical. Reset after source gaps or changing calibration.
    The library's covariance history is bounded to its default two seconds.
    """

    def __init__(self, model):
        self.model = model
        self._backend_class = _backend()
        if version('meegkit') != model.backend_version:
            raise ASRError('ASR library version differs from training calibration; refit the model')
        self.reset()

    def reset(self):
        model = self.model
        self._processor = self._backend_class(sfreq=model.fs, cutoff=model.settings.cutoff,
            win_len=model.settings.window_seconds, method='euclid')
        self._processor.ab_ = (model.A.copy(), model.B.copy())
        self._processor.state_ = {'M': model.M.copy(), 'T': model.T.copy(), 'R': None}
        self._processor._fitted = True
        self.last_chunk_corrected = False

    def process(self, samples):
        self.last_chunk_corrected = False
        data = _validated_data(samples, len(self.model.channels))
        if not len(data):
            return data.copy()
        step = max(1, int(round(self.model.settings.step_seconds * self.model.fs)))
        output = np.empty_like(data)
        for start in range(0, len(data), step):
            block = data[start:start + step]
            previous = self._processor.state_['R']
            try:
                cleaned = self._processor.transform(block.T.copy() * self.model.input_scale).T / self.model.input_scale
            except Exception as exc:
                raise ASRError('ASR processing failed: ' + str(exc)) from exc
            if cleaned.shape != block.shape or not np.isfinite(cleaned).all():
                raise ASRError('ASR backend returned invalid data; reset before continuing')
            # The backend uses identity when all components pass its thresholds.
            # Include the previous matrix during its raised-cosine release blend.
            identity = np.eye(len(self.model.channels))
            current = self._processor.state_['R']
            nontrivial = lambda matrix: matrix is not None and not np.allclose(
                matrix, identity, rtol=1e-7, atol=1e-9)
            self.last_chunk_corrected |= bool(nontrivial(current) or
                (len(block) > 1 and nontrivial(previous)))
            output[start:start + len(block)] = cleaned
        return output
