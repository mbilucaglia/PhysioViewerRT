"""Measure NPZ save/load on disposable synthetic recordings, without processing."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from physiolab.calibration import save_calibration, load_calibration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    fs, channels = 256, 32
    samples = np.random.default_rng(2026).normal(size=(fs * args.seconds, channels))
    streams = {'EEG': {'data': samples, 'timestamps': np.arange(len(samples)) / fs,
                       'fs': fs, 'channels': [f'EEG{i}' for i in range(channels)]}}
    results = {'seconds': args.seconds, 'channels': channels, 'sample_rate': fs,
               'array_bytes': samples.nbytes + streams['EEG']['timestamps'].nbytes}
    with tempfile.TemporaryDirectory(dir=ROOT / '.local') as directory:
        path = Path(directory) / 'synthetic.npz'
        save_ms, load_ms = [], []
        for _ in range(args.repeats):
            start = time.perf_counter()
            save_calibration(path, 'BSL', streams, {})
            save_ms.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            load_calibration(path, 'BSL')
            load_ms.append((time.perf_counter() - start) * 1000)
        results.update(file_bytes=path.stat().st_size, save_ms=save_ms, load_ms=load_ms,
                       save_median_ms=statistics.median(save_ms),
                       load_median_ms=statistics.median(load_ms))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
