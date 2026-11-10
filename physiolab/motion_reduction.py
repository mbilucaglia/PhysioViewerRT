"""Causal ACC alignment and multireference NLMS; no GUI or transport dependencies."""
from dataclasses import dataclass
import re
import numpy as np
from .motion_recording import MOTION_ALGORITHM, validate_static_calibration


def is_acc_stream(info):
    words = re.findall(r'[a-z]+', f'{info.name()} {info.type()}'.lower())
    return any(w in ('acc', 'accel', 'accelerometer', 'accelerometry', 'acceleration', 'imu')
               or w.startswith('accelerom') for w in words)


def acc_axes(labels):
    """Recognize explicit axis labels, including axes embedded in mixed streams."""
    normalized = [re.sub('[^a-z0-9]', '', label.lower()) for label in labels]
    result = []
    for axis in 'xyz':
        aliases = {axis, 'acc'+axis, 'accel'+axis, 'accelerometer'+axis,
                   'acceleration'+axis, axis+'acc', axis+'accel'}
        matches = [i for i, name in enumerate(normalized) if name in aliases]
        if len(matches) != 1:
            return None
        result.append(matches[0])
    return tuple(result)


def static_acc_calibration(values, timestamps, fs: float) -> tuple[tuple[float, ...], float]:
    """Estimate static offset and conservative residual energy from 5 fresh seconds."""
    x, t = np.asarray(values, dtype=float), np.asarray(timestamps, dtype=float)
    if (x.shape != (len(t), 3) or len(t) < max(4, int(4.8*fs))
            or not np.isfinite(x).all() or not np.isfinite(t).all()
            or t[-1]-t[0] < 4.8 or np.any(np.diff(t) <= 0)
            or np.any(np.diff(t) > 3/fs)):
        raise ValueError('ACC calibration requires 5 continuous seconds of valid samples')
    zero = np.median(x, axis=0)
    gravity = float(np.linalg.norm(zero))
    if gravity < 1e-6:
        raise ValueError('ACC calibration requires a gravity-bearing accelerometer')
    residual = np.linalg.norm(x-zero, axis=1)
    if np.quantile(residual, .95) > .05*gravity:
        raise ValueError('Too much movement: stay still and repeat ACC calibration')
    return tuple(float(v) for v in zero), float((1.5*np.quantile(residual, .99))**2)


@dataclass(frozen=True)
class MotionReference:
    info: object
    indices: tuple
    enabled: bool = False
    intervention_threshold_mg: float = 5.
    static_calibration: tuple | None = None

    def __post_init__(self):
        validate_static_calibration(self.static_calibration)
        if (len(self.indices) != 3 or len(set(self.indices)) != 3
                or any(not isinstance(i, int) or i < 0 or i >= self.info.channel_count()
                       for i in self.indices)):
            raise ValueError('Select three distinct ACC channels (X, Y, Z)')
        if not np.isfinite(self.info.nominal_srate()) or self.info.nominal_srate() <= 0:
            raise ValueError('ACC requires a regular positive sampling rate')
        if (not np.isfinite(self.intervention_threshold_mg)
                or self.intervention_threshold_mg <= 0):
            raise ValueError('ACC intervention threshold must be finite and positive')

    def metadata(self):
        metadata = dict(algorithm=MOTION_ALGORITHM, source_id=self.info.source_id() or self.info.uid(),
                        channels=list(self.indices),
                        fs=float(self.info.nominal_srate()), enabled=self.enabled)
        # Preserve compatibility with recordings created before the default
        # 5 mg threshold was user-configurable; that was already the fixed gate.
        if self.intervention_threshold_mg != 5.:
            metadata['intervention_threshold_mg'] = float(self.intervention_threshold_mg)
        if self.static_calibration is not None:
            metadata["static_calibration"] = [list(self.static_calibration[0]), self.static_calibration[1]]
        return metadata

    def validate_primary(self, info, indices):
        same = (info.uid() == self.info.uid() if info.uid() and self.info.uid()
                else info.source_id() == self.info.source_id())
        if self.enabled and same and set(indices).intersection(self.indices):
            raise ValueError('ACC reference channels must not overlap primary signal channels')


class MotionCanceller:
    """Zero-order causal resampling; reset adaptation on missing/invalid references.

    The reference has a 0.5 Hz DC remover (gravity); adaptation targets a
    centered primary signal while subtraction preserves its original baseline.
    mu=0.03, 150 ms FIR history (at most 64 taps per axis), 1 s warmup.
    """
    def __init__(self, fs, channels, reference_fs, intervention_threshold_mg=5., static_calibration=None):
        validate_static_calibration(static_calibration)
        self.static_calibration = static_calibration
        self.fs, self.channels = float(fs), int(channels)
        if min(self.fs, reference_fs) <= 0 or not np.isfinite([fs, reference_fs]).all():
            raise ValueError('Sampling rates must be finite and positive')
        if (not np.isfinite(intervention_threshold_mg)
                or intervention_threshold_mg <= 0):
            raise ValueError('ACC intervention threshold must be finite and positive')
        self.intervention_threshold_mg = float(intervention_threshold_mg)
        self.taps = max(2, min(64, round(.15 * fs)))
        self.max_age = min(.25, 3. / reference_fs)
        self.capacity = max(4, int(reference_fs * 40))
        self.times = np.empty(0)
        self.values = np.empty((0, 3))
        self.status = 'ACC waiting'
        self.latest = None
        self.reset()

    def reset(self):
        self.weights = np.zeros((self.channels, self.taps * 3))
        self.delay = np.zeros((self.taps, 3))
        self.reference_mean = self.target_mean = None
        self.last_time = None
        self.trained = 0
        self.reference_floor = None
        self.peak_energy = 0.

    def append(self, samples, timestamps):
        values, times = np.asarray(samples, dtype=float), np.asarray(timestamps, dtype=float)
        if values.shape != (len(times), 3):
            raise ValueError('ACC samples must have three axes and matching timestamps')
        last = self.times[-1] if len(self.times) else -np.inf
        keep = []
        for i, stamp in enumerate(times):
            if np.isfinite(stamp) and stamp > last:
                keep.append(i)
                last = stamp
        if keep:
            # Keep invalid values as explicit holes: never hold an old valid ACC
            # value across a reported NaN/Inf sample.
            self.times = np.concatenate((self.times, times[keep]))[-self.capacity:]
            self.values = np.concatenate((self.values, values[keep]))[-self.capacity:]
            self.latest = tuple(float(v) for v in self.values[-1])

    def process(self, samples, timestamps):
        x = np.asarray(samples, dtype=float)
        stamps = np.asarray(timestamps, dtype=float)
        if x.shape != (len(stamps), self.channels) or not np.isfinite(x).all():
            raise ValueError('Invalid primary signal for ACC cancellation')
        y = x.copy()
        indices = np.searchsorted(self.times, stamps, side='right') - 1
        valid_count = 0
        moving_count = 0
        for i, (stamp, idx) in enumerate(zip(stamps, indices)):
            if (not np.isfinite(stamp) or idx < 0 or stamp-self.times[idx] > self.max_age
                    or not np.isfinite(self.values[idx]).all()):
                self.reset()
                continue
            if self.last_time is not None and (stamp <= self.last_time or
                    stamp-self.last_time > max(.25, 3/self.fs)):
                self.reset()
            self.last_time = stamp
            ref = self.values[idx]
            gravity = np.linalg.norm(ref)
            if self.static_calibration is not None:
                zero, noise_energy = self.static_calibration
                gravity = np.linalg.norm(zero)
                ref = ref - np.asarray(zero)
            if self.reference_mean is None:
                self.reference_mean, self.target_mean = ref.copy(), x[i].copy()
                # Express the minimum as a fraction of measured gravity so it
                # works whether the stream reports m/s² or g.
                # Do not normalize adaptation by a vanishing ACC residual.
                threshold = self.intervention_threshold_mg / 1000.
                self.reference_floor = max(1e-8, (threshold*gravity)**2)*self.delay.size
            if self.static_calibration is not None:
                self.reference_floor = max((self.intervention_threshold_mg*gravity/1000.)**2, noise_energy)*self.taps
            self.reference_mean += (1-np.exp(-2*np.pi*.5/self.fs))*(ref-self.reference_mean)
            self.target_mean += (1-np.exp(-2*np.pi*.1/self.fs))*(x[i]-self.target_mean)
            self.delay[1:] = self.delay[:-1]
            self.delay[0] = ref-self.reference_mean
            u = self.delay.ravel()
            energy = float(u @ u)
            self.peak_energy = max(energy, self.peak_energy*np.exp(-1/(60*self.fs)))
            valid_count += 1
            if energy <= max(self.reference_floor, .0025*self.peak_energy):
                self.weights.fill(0.)
                self.trained = 0
                continue
            prediction = self.weights @ u
            error = x[i]-self.target_mean-prediction
            if energy > 1e-12:
                self.weights += .03 * np.outer(error, u) / (energy+1e-8)
            self.trained += 1
            # Fade in cancellation after the first second of adaptation.
            blend = float(np.clip((self.trained-self.fs)/self.fs, 0, 1))
            y[i] -= blend * prediction
            moving_count += 1
        if not np.isfinite(y).all() or not np.isfinite(self.weights).all():
            self.reset()
            self.status = 'ACC bypass: numerical instability'
            return x.copy()
        self.status = ('ACC bypass: missing/stale reference' if not valid_count else
                       'ACC partial bypass' if valid_count < len(x) else
                       'ACC monitoring: low motion' if not moving_count else
                       'ACC warming up' if self.trained < 2*self.fs else 'ACC NLMS active')
        return y
