"""Published-method waveform reducers and an explicitly buffered online adapter.

PPG: Biswas et al. 2019, doi:10.1007/978-981-10-8863-6_10 (db6/DWT/SURE).
SC: Shukla et al. 2018, doi:10.1016/j.bspc.2018.01.009; mathematical details
cross-checked against the authors' EP3466322A1 disclosure (Haar/SWT/Laplace).
Hampel: standard centered median/MAD replacement, as documented by HeartPy;
SC use is a general robust-filter application, not a claim of SC validation.
See docs/PERIPHERAL_REDUCTION_EVIDENCE.md for all adapter choices/departures.
"""
from fractions import Fraction
import importlib
import math
import numpy as np
from scipy.signal import resample_poly
from numpy.lib.stride_tricks import sliding_window_view

METHODS = ('off', 'hampel', 'wavelet')
ALGORITHM_VERSION = 1
WINDOW_SECONDS = 8.
HOP_SECONDS = 1.
HAMPEL_RADIUS = 3
HAMPEL_SIGMA = 3.
SC_ARTIFACT_PROPORTION = .10


def require_reduction_backend(method):
    """Fail before changing reception or buffering if Wavelet cannot import."""
    if method != 'wavelet':
        return
    try:
        importlib.import_module('pywt')
    except (ImportError, OSError, ValueError) as exc:
        raise RuntimeError(
            f'Wavelet unavailable: {exc}. Run setup_windows.cmd in the project '
            'folder to install its required PyWavelets dependency.') from exc


def sure_threshold(coefficients, sigma):
    """SURE soft-threshold risk minimized at the observed coefficient magnitudes.

    Unit-noise formulation, scaled back by sigma (Donoho/Johnstone; MATLAB
    thselect/rigrsure). No universal-threshold substitution or clipping of data.
    """
    values = np.asarray(coefficients, dtype=float).ravel()
    if not len(values) or not np.isfinite(sigma) or sigma <= np.finfo(float).eps:
        return 0.
    squares = np.sort((values/sigma)**2)
    count = len(squares)
    indices = np.arange(1,count+1)
    risk = count-2*indices+np.cumsum(squares)+(count-indices)*squares
    return float(sigma*np.sqrt(squares[np.argmin(risk)]))


def hampel_block(samples, radius=HAMPEL_RADIUS):
    """Seven-sample centered median/MAD outlier replacement; no detrending."""
    x = np.asarray(samples,dtype=float)
    if len(x) < 2:
        return x.copy()
    padded = np.pad(x,((radius,radius),(0,0)),mode='reflect')
    windows = sliding_window_view(padded,2*radius+1,axis=0)
    medians = np.median(windows,axis=-1)
    sigma = 1.4826*np.median(np.abs(windows-medians[:,:,None]),axis=-1)
    outliers = np.abs(x-medians) > HAMPEL_SIGMA*sigma
    return np.where(outliers,medians,x)


def _resample(x, source_hz, target_hz):
    ratio = Fraction(float(target_hz)/float(source_hz)).limit_denominator(1024)
    return resample_poly(x,ratio.numerator,ratio.denominator,axis=0,padtype='line'), ratio


def ppg_wavelet_block(samples, fs):
    """db6, five-level DWT and rigrsure soft shrinking at 60 Hz.

    Online choice: 8 s windows instead of the study's 30 s recordings;
    finest-detail MAD noise scaling and symmetric extension are explicit
    adapter conventions. Includes A5 as stated in the paper's procedure.
    """
    import pywt
    x = np.asarray(samples,dtype=float)
    reduced, ratio = _resample(x,fs,60.)
    if len(reduced) < 352:
        raise ValueError('PPG db6 level-5 denoising requires at least 352 samples at 60 Hz')
    output = np.empty_like(reduced)
    for channel in range(x.shape[1]):
        coefficients = pywt.wavedec(reduced[:,channel],'db6',mode='symmetric',level=5)
        sigma = float(np.median(np.abs(coefficients[-1]))/.6744897501960817)
        repaired = [pywt.threshold(c,sure_threshold(c,sigma),mode='soft')
                    if sigma > np.finfo(float).eps else c.copy() for c in coefficients]
        output[:,channel] = pywt.waverec(repaired,'db6',mode='symmetric')[:len(reduced)]
    restored = resample_poly(output,ratio.denominator,ratio.numerator,axis=0,padtype='line')
    return restored[:len(x)].copy()


def laplace_limit(coefficients, proportion=SC_ARTIFACT_PROPORTION):
    """Positive two-sided Laplace tail limit, P(|D|>T)=proportion.

    Uses the mathematically ordered +/- quantiles; the companion disclosure's
    rendered equation has a sign/order inconsistency for log(delta)<0.
    """
    if not 0 < proportion < 1:
        raise ValueError('Artifact proportion must lie between zero and one')
    return -np.mean(np.abs(coefficients),axis=0)*np.log(proportion)


def sc_wavelet_block(samples, fs):
    """Haar SWT, high-band zeroing and Laplace-tail zeroing, then inverse SWT."""
    import pywt
    x = np.asarray(samples,dtype=float)
    analysis_hz = 2**round(math.log2(fs))
    reduced, ratio = _resample(x,fs,analysis_hz)
    levels = int(math.log2(analysis_hz))+2
    # Authors permit boundary padding but do not specify its extent/mode.
    # Four seconds of reflected data on both sides; pad to SWT divisibility.
    pad = round(4*analysis_hz)
    multiple = 2**levels
    extra = (-(len(reduced)+2*pad)) % multiple
    padded = np.pad(reduced,((pad,pad+extra),(0,0)),mode='reflect')
    pairs = pywt.swt(padded,'haar',level=levels,axis=0,norm=False)
    repaired = []
    for index,(approximation,detail) in enumerate(pairs):
        level = levels-index
        if analysis_hz/2**level >= 1.:
            cleaned = np.zeros_like(detail)  # bands at/above 0.5 Hz
        else:
            limit = laplace_limit(detail[pad:pad+len(reduced)])
            cleaned = np.where(np.abs(detail) <= limit,detail,0.)
        repaired.append((approximation,cleaned))
    output = pywt.iswt(repaired,'haar',axis=0,norm=False)[pad:pad+len(reduced)]
    restored = resample_poly(output,ratio.denominator,ratio.numerator,axis=0,padtype='line')
    return restored[:len(x)].copy()


class PeripheralReducer:
    """Immutable emitted samples, exact input timestamps, bounded raw context.

    Hampel finalizes only samples with 3 real future samples available. Wavelet
    waits for its first 8-second window, emits that window, then the latest new
    1-second interval from each trailing window. Boundary extension is internal,
    never returned as acquired samples. Tail samples await the next full hop.
    """
    def __init__(self,kind,fs,channels,method):
        if kind not in ('PPG','EDA') or method not in METHODS[1:]:
            raise ValueError('Unsupported peripheral artifact reduction method')
        if not math.isfinite(fs) or fs < 4 or channels < 1:
            raise ValueError('Artifact reduction requires regular sampling of at least 4 Hz')
        require_reduction_backend(method)
        self.kind,self.fs,self.channels,self.method = kind,float(fs),channels,method
        self.window = round(WINDOW_SECONDS*fs)
        self.hop = max(1,round(HOP_SECONDS*fs))
        self.raw = np.empty((0,channels))
        self.times = np.empty(0)
        self.start = self.total = self.emitted = 0

    def push(self,samples,timestamps=None):
        x = np.asarray(samples,dtype=float)
        if x.ndim != 2 or x.shape[1] != self.channels or not np.isfinite(x).all():
            raise ValueError('Artifact reduction requires finite samples by channels')
        times = (np.arange(self.total,self.total+len(x))/self.fs if timestamps is None
                 else np.asarray(timestamps,dtype=float))
        if len(times) != len(x) or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
            raise ValueError('Artifact reduction requires aligned increasing timestamps')
        self.raw = np.concatenate((self.raw,x))
        self.times = np.concatenate((self.times,times))
        self.total += len(x)
        raw_out, clean_out, time_out = [],[],[]
        if self.method == 'hampel':
            stop = self.total-HAMPEL_RADIUS if self.total >= 2*HAMPEL_RADIUS+1 else 0
            if stop > self.emitted:
                left,right = self.emitted-self.start,stop-self.start
                raw_out.append(self.raw[left:right].copy())
                clean_out.append(hampel_block(self.raw)[left:right])
                time_out.append(self.times[left:right].copy())
                self.emitted = stop
            keep = max(0,self.emitted-HAMPEL_RADIUS)
        else:
            next_end = self.window if self.emitted == 0 else self.emitted+self.hop
            block = ppg_wavelet_block if self.kind == 'PPG' else sc_wavelet_block
            while self.total >= next_end:
                left,right = next_end-self.window-self.start,next_end-self.start
                source = self.raw[left:right]
                repaired = block(source,self.fs)
                count = self.window if self.emitted == 0 else self.hop
                raw_out.append(source[-count:].copy())
                clean_out.append(repaired[-count:].copy())
                time_out.append(self.times[right-count:right].copy())
                self.emitted = next_end
                next_end += self.hop
            keep = max(0,self.emitted-self.window)
        discard = keep-self.start
        self.raw,self.times = self.raw[discard:].copy(),self.times[discard:].copy()
        self.start = keep
        if not raw_out:
            return np.empty((0,self.channels)),np.empty((0,self.channels)),np.empty(0)
        return np.concatenate(raw_out),np.concatenate(clean_out),np.concatenate(time_out)
