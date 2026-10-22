"""Native GPU microbenchmark; run separate processes with and without --cold.

Measures waveform upload and synchronous draw, not end-to-end LSL latency.
Warmup is normally spread over GUI ticks while the user configures Sources.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtWidgets import QApplication
from physiolab.vispy_raw import VisPyRawPlot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cold', action='store_true', help='Skip Sources warmup')
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    plot = VisPyRawPlot('EEG')
    plot.widget.resize(1000, 500)
    report = {'warmup': not args.cold, 'transitions': []}
    try:
        if not args.cold:
            start = time.perf_counter()
            while plot.warm_channels(32, 5., 256.):
                app.processEvents()
            report['warmup_ms'] = round((time.perf_counter()-start)*1000., 1)
        times = np.arange(2560) / 256.
        for count in (8, 32):
            values = np.tile(np.sin(times[:, None]*20), (1, count)) + 6*np.arange(count)
            frame = (times, values, values, None, None, tuple(map(str, range(count))))
            start, calls = time.perf_counter(), 0
            while plot.channel_count != count:
                plot.set_frame(frame, 0., 5., nominal_fs=256.)
                calls += 1
            prepared = time.perf_counter()
            plot.canvas.render()
            report['transitions'].append({
                'channels': count, 'preparation_rounds': calls,
                'upload_ms': round((prepared-start)*1000., 1),
                'draw_ms': round((time.perf_counter()-prepared)*1000., 1),
            })
    finally:
        plot.close()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
