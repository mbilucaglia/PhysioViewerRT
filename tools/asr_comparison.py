"""Reproducible matched ASR comparison; synthetic evidence, not clinical validation.

Run from repository root: python tools/asr_comparison.py --output .test-tmp/asr-comparison
"""
import argparse
import json
from importlib.metadata import version
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from physiolab.eeg_asr import StreamingASR, fit_asr
from physiolab.metric_observation import source_configuration
from physiolab.processing import Processor


FS = 128
NAMES = ['F3', 'F4', 'O1', 'O2']
CHUNK = 16


def replay(data, model=None):
    cleaner = StreamingASR(model) if model is not None else None
    processor = Processor('EEG', FS, len(NAMES), NAMES,
                          sample_transform=cleaner.process if cleaner else None)
    output = []
    for start in range(0, len(data), CHUNK):
        processor.push(data[start:start + CHUNK])
        output.append(processor.last_filtered_chunk.copy())
    return np.concatenate(output)


def signal(seconds, seed):
    rng = np.random.default_rng(seed)
    t = np.arange(seconds * FS) / FS
    return np.column_stack([10 * np.sin(2 * np.pi * (9 + i * .5) * t + i)
                            for i in range(4)]) + rng.normal(0, 2, (len(t), 4))


def run(output, seed=2026):
    output.mkdir(parents=True, exist_ok=True)
    training = signal(60, seed)
    config = source_configuration('EEG', FS, NAMES, {}, {}, ['uV'] * 4)
    model = fit_asr(replay(training), FS, NAMES, config)
    clean = signal(30, seed + 1)  # Independent evaluation, never fitted.
    contaminated = clean.copy()
    t = np.arange(len(clean)) / FS
    artifact_mask = (t >= 10) & (t < 14)
    contaminated[artifact_mask, 0] += 1000 * np.sin(2 * np.pi * 4 * t[artifact_mask])
    reference = replay(clean)
    off = replay(contaminated)
    on = replay(contaminated, model)
    clean_on = replay(clean, model)
    if any(x.shape != clean.shape or not np.isfinite(x).all()
           for x in (reference, off, on, clean_on)):
        raise RuntimeError('Replay must preserve finite samples and every channel')
    # Exclude startup and report clean preservation on an independent clean replay.
    clean_mask = t >= 5
    rms = lambda x: np.sqrt(np.mean(x ** 2, axis=0))
    error_off = rms((off - reference)[artifact_mask])
    error_on = rms((on - reference)[artifact_mask])
    clean_error = rms((clean_on - reference)[clean_mask])
    clean_rms = rms(reference[clean_mask])
    report = {
        'seed': seed, 'fs_hz': FS, 'channels': NAMES, 'chunk_samples': CHUNK,
        'training_seconds': 60, 'evaluation_seconds': 30, 'cutoff': model.settings.cutoff,
        'artifact': '1000 uV, 4 Hz sinusoid added to F3 from 10 to 14 seconds before filtering',
        'artifact_error_rms_uV_asr_off': error_off.tolist(),
        'artifact_error_rms_uV_asr_on': error_on.tolist(),
        'F3_artifact_error_reduction_percent': float(100 * (1 - error_on[0] / error_off[0])),
        'independent_clean_replay_normalized_rmse': (clean_error / clean_rms).tolist(),
        'versions': {name: version(name) for name in ('numpy', 'scipy', 'meegkit')},
        'limitations': 'One synthetic artifact and seed; no clinical efficacy claim. RMSE uses known synthetic clean reference. ASR is chunk-dependent.'}
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    np.savez_compressed(output / 'matched-recording.npz', timestamps=t, raw=contaminated,
                        clean_raw=clean, training_raw=training, filtered_reference=reference,
                        asr_off=off, asr_on=on, clean_asr_on=clean_on, channels=NAMES, fs=FS)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True, sharey=True)
    for ax, values, label in zip(axes, (off, on), ('ASR off', 'ASR on')):
        ax.plot(t, values[:, 0], color='#312b79', lw=.8, label=label)
        ax.plot(t, reference[:, 0], color='#36a269', lw=.65, label='Known clean reference (same filters)')
        ax.axvspan(10, 14, color='orange', alpha=.15)
        ax.set_ylabel('F3 (µV)')
        ax.legend(loc='upper right')
        ax.grid(alpha=.2)
    axes[-1].set(xlabel='Time (s)', xlim=(8, 17))
    fig.suptitle('Identical synthetic EEG samples · identical axes · fixed ASR cutoff 20')
    fig.tight_layout()
    fig.savefig(output / 'matched-comparison.png', dpi=150)
    plt.close(fig)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('.test-tmp/asr-comparison'))
    parser.add_argument('--seed', type=int, default=2026)
    args = parser.parse_args()
    run(args.output, args.seed)
