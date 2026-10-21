"""EYC/BSL calibration analysis and safe portable .npz storage."""
import json
from datetime import datetime, timezone

import numpy as np
from scipy.signal import welch

DURATION_SECONDS = 60.0
POSTERIOR = {
    'O1','O2','OZ','O3','O4','O9','O10',
    'PO3','PO4','PO7','PO8','PO9','PO10','POZ',
    'P1','P2','P3','P4','P5','P6','P7','P8','P9','P10','PZ',
    'TP7','TP8','TP9','TP10','T5','T6','T7','T8',
}


def posterior_indices(labels):
    """Use posterior and temporo-occipital channel labels only."""
    return [i for i, label in enumerate(labels) if str(label).strip().upper() in POSTERIOR]


def analyze_eyc(eeg):
    """Posterior PSD: Hann Welch 1 s, 50% overlap; spectral CoG 7–13 Hz."""
    x = np.asarray(eeg['data'], dtype=float)
    fs = float(eeg['fs'])
    names = list(eeg['channels'])
    idx = posterior_indices(names)
    if not idx:
        raise ValueError('EYC requires labeled posterior EEG channels (e.g. O1/O2, POz, P3/P4).')
    if x.ndim != 2 or x.shape[1] != len(names) or fs < 32 or x.shape[0] < 30 * fs:
        raise ValueError('EYC needs at least 30 s of posterior EEG sampled at >= 32 Hz.')
    data = x[:, idx]
    if not np.isfinite(data).all():
        raise ValueError('EYC contains non-finite posterior EEG values.')
    n = int(round(fs))
    freq, psd = welch(data, fs=fs, window='hann', nperseg=n,
                      noverlap=n // 2, detrend='constant', axis=0,
                      scaling='density')
    mean_psd = np.mean(psd, axis=1)
    mask = (freq >= 7) & (freq <= 13)
    weight = mean_psd[mask]
    total = float(np.sum(weight))
    if len(weight) < 3 or not np.isfinite(total) or total <= 0:
        raise ValueError('No reliable nonzero alpha-band PSD for IAF estimation.')
    cog = float(np.sum(freq[mask] * weight) / total)
    return {
        'iaf_hz': cog, 'alpha_range_hz': [7, 13],
        'posterior_channels': [names[i] for i in idx],
        'psd_hz': freq.tolist(), 'mean_psd': mean_psd.tolist(),
        'method': 'Welch Hann 1-second segments; 50% overlap; mean posterior PSD; 7–13 Hz center of gravity',
    }


def summarize_metric(values):
    """Compute reusable reference factors from valid metric observations."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 5:
        return None
    q1, q3 = np.percentile(v, [25, 75])
    med = float(np.median(v))
    return {'mu': float(np.mean(v)),
            'sigma': float(np.std(v, ddof=1)),
            'median': med, 'iqr': float(q3-q1),
            'mad': float(np.median(np.abs(v-med))),
            'q1': float(q1), 'q3': float(q3),
            'minimum': float(np.min(v)), 'maximum': float(np.max(v)),
            'valid_windows': len(v)}


def analyze_bsl(streams, iaf_hz=10.0):
    """Summarize EEG, EDA, PPG and EI from time-aligned 0.5-second windows.

    HR and SCL are standardized within the complete BSL signals (not
    relative to an earlier BSL reference). Missing values remain missing.
    """
    from .processing import Processor
    from .emotion import baseline_ei
    summaries, series = {}, {}
    for kind, item in streams.items():
        if kind not in ('EEG','EDA','PPG'):
            continue
        fs = float(item['fs'])
        data = np.asarray(item['data'], dtype=float)
        stamps = np.asarray(item.get('timestamps', []), dtype=float)
        if data.ndim != 2 or len(data) < fs or not np.isfinite(data).all():
            continue
        if len(stamps) != len(data) or not np.isfinite(stamps).all():
            # Do not fabricate timestamps for multimodal EI alignment.
            continue
        proc = Processor(kind, fs, data.shape[1], item['channels'], iaf_hz=iaf_hz)
        hop = max(1, round(fs*.5))
        sequence = {}
        for start in range(0, len(data), hop):
            metric = proc.push(data[start:start+hop])
            if metric is None:
                continue
            index = min(start+hop, len(stamps)) - 1
            t = float(stamps[index])
            for key, val in metric.items():
                if key == 'IAF' or not isinstance(val, (float,int)):
                    continue
                sequence.setdefault(key, []).append((t, float(val) if np.isfinite(val) else np.nan))
        series[kind] = sequence
        for key, observations in sequence.items():
            summary = summarize_metric([v for _,v in observations])
            if summary is not None:
                summaries.setdefault(kind, {})[key] = summary

    hr = series.get('PPG', {}).get('HR', [])
    scl = series.get('EDA', {}).get('SCL', [])
    if hr and scl:
        # Align to half-second bins using original LSL timestamps and preserve
        # invalid slots; no zip of valid-only lists that shifts missing HR.
        start = max(hr[0][0], scl[0][0])
        stop = min(hr[-1][0], scl[-1][0])
        if stop-start >= 50:
            grid = np.arange(start, stop, .5)
            def grid_values(samples):
                buckets = np.full(len(grid), np.nan)
                for t, val in samples:
                    i = int(round((t-start)/.5))
                    if 0 <= i < len(grid) and abs(t-grid[i]) <= .25:
                        buckets[i] = val
                return buckets
            ei = baseline_ei(grid_values(hr), grid_values(scl))
            summary = summarize_metric(ei)
            if summary is not None:
                summaries['EI'] = {'EI': summary}
    return {'iaf_hz_used': float(iaf_hz), 'metrics': summaries,
            'method': '1 s windows / 50% overlap, EI from within-BSL z-scored HR and SCL'}

def normalize(value, reference=None, mode='identity'):
    """Reference-frozen transform. No baseline => identity (uncalibrated)."""
    if mode == 'identity' or reference is None:
        return float(value)
    if mode == 'zscore':
        center, spread = reference['mu'], reference['sigma']
    elif mode == 'zmad':
        center, spread = reference['median'], 1.4826 * reference['mad']
    elif mode == 'robust_iqr':
        center, spread = reference['median'], reference['iqr'] / 1.349
    elif mode == 'minmax':
        center, spread = reference['minimum'], reference['maximum']-reference['minimum']
    else:
        raise ValueError('Unknown normalization mode')
    if not np.isfinite(spread) or spread <= 1e-12:
        return None
    return float((value-center)/spread)


def samples_after_timestamp(data, timestamps, boundary):
    """Keep original paired LSL samples strictly after capture start.

    A source may have accumulated queued chunks during a GUI interaction;
    these must not enter a later 60-second calibration recording.
    """
    x = np.asarray(data, dtype=float)
    ts = np.asarray(timestamps, dtype=float)
    if x.ndim != 2 or ts.ndim != 1 or len(x) != len(ts):
        raise ValueError('Calibration samples and timestamps must align')
    valid = np.isfinite(ts)
    if boundary is not None:
        valid &= ts > float(boundary)
    return x[valid], ts[valid]


def save_calibration(path, kind, streams, analysis):
    """Persist raw samples, LSL timestamps, labels, fs and summaries without pickle."""
    if kind not in ('EYC', 'BSL'):
        raise ValueError('Unknown calibration type.')
    meta = {
        'schema': 1, 'type': kind, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'duration_requested_s': DURATION_SECONDS, 'streams': {},
        'analysis': analysis,
    }
    arrays = {}
    for modality, item in streams.items():
        if modality not in ('EEG', 'EDA', 'PPG'):
            continue
        data = np.asarray(item['data'], dtype=float)
        stamp = np.asarray(item['timestamps'], dtype=float)
        if data.ndim != 2 or len(data) != len(stamp) or not len(data) or not np.isfinite(data).all() or not np.isfinite(stamp).all():
            raise ValueError(f'Invalid capture for {modality}')
        arrays[f'{modality}_data'] = data
        arrays[f'{modality}_timestamps'] = stamp
        meta['streams'][modality] = {'fs': float(item['fs']), 'channels': list(item['channels']),
                                     'samples': int(len(data)),
                                     'recorded_span_s': float(stamp[-1]-stamp[0])}
    if kind == 'EYC' and 'EEG' not in meta['streams']:
        raise ValueError('EYC EEG stream missing')
    if not meta['streams']:
        raise ValueError('No streams collected')
    arrays['metadata'] = np.array(json.dumps(meta))
    with open(path, 'wb') as fh:
        np.savez_compressed(fh, **arrays)


def load_calibration(path, expected_kind):
    with np.load(path, allow_pickle=False) as fh:
        meta = json.loads(str(fh['metadata'].item()))
        if meta.get('schema') != 1 or meta.get('type') != expected_kind:
            raise ValueError('Unexpected calibration type/schema')
        streams = {}
        for modality, descriptor in meta['streams'].items():
            data = np.array(fh[f'{modality}_data'], dtype=float)
            stamps = np.array(fh[f'{modality}_timestamps'], dtype=float)
            if data.ndim != 2 or len(data) != len(stamps) or data.shape[1] != len(descriptor['channels']):
                raise ValueError('Invalid file signal dimensions')
            streams[modality] = {'data': data, 'timestamps': stamps,
                                 'fs': descriptor['fs'], 'channels': descriptor['channels']}
    return meta, streams
