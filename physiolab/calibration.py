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


def analyze_eyc(eeg, eeg_asr_model=None):
    """Posterior PSD: Hann Welch 1 s, 50% overlap; spectral CoG 7–13 Hz."""
    x = np.asarray(eeg['data'], dtype=float)
    fs = float(eeg['fs'])
    names = list(eeg['channels'])
    idx = posterior_indices(names)
    if not idx:
        raise ValueError('EYC requires labeled posterior EEG channels (e.g. O1/O2, POz, P3/P4).')
    if x.ndim != 2 or x.shape[1] != len(names) or fs < 32 or x.shape[0] < 30 * fs:
        raise ValueError('EYC needs at least 30 s of posterior EEG sampled at >= 32 Hz.')
    # Analyze the same ordered channels after the live preprocessing chain.
    from .processing import Processor
    transform = _eeg_transform(eeg, eeg_asr_model)
    processor = Processor('EEG', fs, len(names), names,
                          preprocessing=eeg.get('preprocessing'), sample_transform=transform)
    chunks = []
    hop = max(1, round(fs*.5))
    for start in range(0, len(x), hop):
        processor.push(x[start:start+hop])
        chunks.append(processor.last_filtered_chunk.copy())
    data = np.concatenate(chunks)[:, idx]
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
        'eeg_asr_model_id': eeg_asr_model.model_id if eeg_asr_model else None,
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


def _eeg_transform(eeg, model):
    if model is None:
        return None
    from .asr_tasks import eeg_configuration
    from .eeg_asr import StreamingASR
    if eeg_configuration(eeg) != model.source_configuration:
        raise ValueError('EEG recording settings differ from ASR training; use matching settings')
    return StreamingASR(model).process


def analyze_bsl(streams, iaf_hz=10.0, eeg_asr_model=None):
    """Analyze metric windows and canonical cvxEDA tonic SCL.

    EI uses the latest available inputs and the same stored HR/SCL mean and
    standard deviation as live processing. Missing estimates remain missing.
    """
    from .processing import Processor
    from .emotion import BaselineEmotionalIndex
    from .metric_observation import source_configuration
    summaries, series, source_configurations = {}, {}, {}
    tonic_metadata = None
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
        proc = Processor(kind, fs, data.shape[1], item['channels'], iaf_hz=iaf_hz,
                         preprocessing=item.get('preprocessing'),
                         sample_transform=_eeg_transform(item, eeg_asr_model) if kind == 'EEG' else None)
        source_configurations[kind] = source_configuration(
            kind, fs, item['channels'], proc.preprocessing, item.get('conversion'),
            item.get('units') or [''] * data.shape[1])
        if kind == 'EEG' and eeg_asr_model is not None:
            source_configurations[kind]['asr_model_id'] = eeg_asr_model.model_id
        hop = max(1, round(fs*.5))
        sequence = {}
        filtered_chunks,filtered_times = [],[]
        for start in range(0, len(data), hop):
            metric = proc.push(data[start:start+hop],timestamps=stamps[start:start+hop])
            if kind == 'EDA' and len(proc.last_filtered_chunk):
                filtered_chunks.append(proc.last_filtered_chunk.copy())
                filtered_times.append(proc.last_timestamps.copy())
            if metric is None:
                continue
            index = min(start+hop, len(stamps)) - 1
            t = float(proc.last_timestamps[-1]) if len(proc.last_timestamps) else float(stamps[index])
            for key, val in metric.items():
                if key == 'IAF' or not (val is None or isinstance(val, (float,int))):
                    continue
                sequence.setdefault(key, []).append((t, float(val) if val is not None and np.isfinite(val) else np.nan))
        series[kind] = sequence
        for key, observations in sequence.items():
            summary = summarize_metric([v for _,v in observations])
            if summary is not None:
                summaries.setdefault(kind, {})[key] = summary

        if kind == 'EDA' and filtered_chunks:
            from .sc_decomposition import TonicSCProcessor, decompose_baseline, sc_pipeline_metadata
            from .display_units import source_display_unit
            unit = source_display_unit(item.get('units', []))
            tonic = TonicSCProcessor(unit=unit)
            observations = decompose_baseline(
                np.concatenate(filtered_chunks), np.concatenate(filtered_times), fs, settings=tonic.settings, unit=unit)
            summary = summarize_metric([observation.value for observation in observations])
            if summary is not None:
                summaries.setdefault(kind, {})['SCL'] = summary
                sequence['SCL'] = [(observation.window_end, observation.value)
                                   for observation in observations]
                tonic_metadata = sc_pipeline_metadata(
                    tonic, proc.preprocessing, item.get('conversion'))

    hr = series.get('PPG', {}).get('HR', [])
    scl = series.get('EDA', {}).get('SCL', [])
    if hr and scl:
        # Replay both metric cadences with the same latest-value policy as live EI.
        hr_reference = summaries.get('PPG', {}).get('HR')
        scl_reference = summaries.get('EDA', {}).get('SCL')
        estimator = BaselineEmotionalIndex(hr_reference, scl_reference)
        events = [(at, 'PPG', value) for at, value in hr]
        events.extend((at, 'EDA', value) for at, value in scl)
        ei_values = []
        for at, kind, measured in sorted(events, key=lambda event: event[0]):
            estimator.update(kind, measured, at)
            value = estimator.value()
            ei_values.append(np.nan if value is None else value)
        summary = summarize_metric(ei_values)
        if summary is not None:
            summaries['EI'] = {'EI': summary}
    return {'iaf_hz_used': float(iaf_hz), 'metrics': summaries, 'tonic_sc': tonic_metadata,
            'source_configurations': source_configurations,
            'method': 'EEG/HR window metrics; SCL from rolling cvxEDA tonic decomposition; '
                      'EI from latest available HR and tonic SCL with fixed BSL reference statistics'}

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
                                     'preprocessing': dict(item.get('preprocessing') or {}),
                                     'conversion': dict(item.get('conversion') or {}),
                                     'source_units': list(item.get('source_units') or []),
                                     'units': list(item.get('units') or []),
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
                                 'fs': descriptor['fs'], 'channels': descriptor['channels'],
                                 'preprocessing': descriptor.get('preprocessing', {}),
                                 'conversion': descriptor.get('conversion', {}),
                                 'source_units': descriptor.get('source_units', []),
                                 'units': descriptor.get('units', [])}
    return meta, streams
