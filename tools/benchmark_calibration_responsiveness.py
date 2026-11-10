"""Compare GUI heartbeat during synchronous and worker-based synthetic NPZ I/O."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from physiolab.gui import MainWindow
from physiolab.calibration import save_calibration, load_calibration


def main():
    app = QApplication.instance() or QApplication([])
    with patch.object(MainWindow, 'refresh'):
        window = MainWindow()
    window.timer.stop()
    fs, channels = 256, 32
    data = np.random.default_rng(2026).normal(size=(fs * 60, channels))
    streams = {'EEG': {'data': data, 'timestamps': np.arange(len(data)) / fs,
                       'fs': fs, 'channels': [f'EEG{i}' for i in range(channels)]}}
    timer = QTimer()
    timer.setInterval(5)
    ticks = []
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    measurements = {}
    try:
        with tempfile.TemporaryDirectory(dir=ROOT / '.local') as folder:
            path = Path(folder) / 'synthetic.npz'
            for operation in ('save', 'load'):
                for mode in ('synchronous', 'worker'):
                    ticks.clear()
                    timer.start()
                    start = time.perf_counter()
                    if mode == 'worker':
                        window._run_calibration_io(operation, path, 'BSL', streams, {})
                    elif operation == 'save':
                        save_calibration(path, 'BSL', streams, {})
                    else:
                        load_calibration(path, 'BSL')
                    finish = time.perf_counter()
                    timer.stop()
                    gaps = np.diff([start, *ticks, finish]) * 1000
                    measurements[f'{operation}_{mode}'] = {
                        'elapsed_ms': (finish - start) * 1000,
                        'gui_heartbeat_count': len(ticks),
                        'largest_heartbeat_gap_ms': float(max(gaps)),
                    }
        print(json.dumps({'array_bytes': data.nbytes + streams['EEG']['timestamps'].nbytes,
                          'measurements': measurements}, indent=2))
    finally:
        timer.stop()
        window.close()
        deadline = time.monotonic() + 5
        while not window._closed and time.monotonic() < deadline:
            app.processEvents()
        if not window._closed:
            raise RuntimeError('Benchmark window did not finish closing')


if __name__ == '__main__':
    main()
