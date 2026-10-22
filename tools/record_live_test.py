r"""Record the real Windows Qt/LSL integration test to MP4.

Optional developer dependency: pip install imageio-ffmpeg
Run: .venv\Scripts\python.exe tools/record_live_test.py
Only the application widget is captured; no desktop or other windows.
"""
import json
import os
from pathlib import Path
import sys
import time
import unittest

os.environ['QT_QPA_PLATFORM'] = 'windows'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import imageio_ffmpeg
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
import tests_gui.test_lsl_integration as integration


class WindowRecording:
    SIZE = (1280, 900)
    FPS = 10

    def __init__(self, window, output):
        self.window = window
        self.started = time.monotonic()
        self.frames = 0
        self.previous = None
        self.timeline = []
        self.last_state = None
        self.errors = []
        self.writer = imageio_ffmpeg.write_frames(
            str(output), self.SIZE, fps=self.FPS, codec='libx264',
            pix_fmt_in='rgba', pix_fmt_out='yuv420p', quality=7,
            macro_block_size=2, output_params=['-movflags', '+faststart'])
        self.writer.send(None)
        self.timer = QTimer(window)
        self.timer.timeout.connect(self.capture)
        self.timer.start(round(1000/self.FPS))

    def capture(self):
        if not self.window.isVisible():
            return
        try:
            elapsed = time.monotonic() - self.started
            expected = int(elapsed*self.FPS)
            # Preserve wall time when the GUI stalls: hold the previous frame
            # for missed capture intervals instead of speeding up the video.
            if self.previous is not None:
                while self.frames < expected:
                    self.writer.send(self.previous)
                    self.frames += 1
            image = self.window.grab().toImage()
            if (image.width(), image.height()) != self.SIZE:
                image = image.scaled(*self.SIZE)
            image = image.convertToFormat(QImage.Format.Format_RGBA8888)
            self.previous = bytes(image.constBits())
            self.writer.send(self.previous)
            self.frames += 1
            w = self.window
            state = (w.tabs.tabText(w.tabs.currentIndex()), w.eeg_display_count.value(),
                     w.raw_display.view_seconds, w.raw_vertical_gains['EEG'].value(),
                     w.eeg_focus_button.isChecked(), w.metric_view_seconds,
                     w.normalization.currentData())
            if state != self.last_state:
                self.timeline.append({'seconds': round(elapsed, 2), 'tab': state[0],
                                      'eeg_channels': state[1], 'raw_seconds': state[2],
                                      'gain': state[3], 'eeg_expanded': state[4],
                                      'metrics_seconds': state[5], 'normalization': state[6]})
                self.last_state = state
        except Exception as exc:
            self.errors.append(str(exc))
            self.timer.stop()

    def finish(self):
        self.timer.stop()
        self.writer.close()


def main():
    output = ROOT / '.test-tmp' / 'app-recording'
    output.mkdir(parents=True, exist_ok=True)
    recordings = []
    original = integration.MainWindow

    class RecordedWindow(original):
        def __init__(self):
            super().__init__()
            self.resize(*WindowRecording.SIZE)
            self.setWindowTitle('PhysioViewerRT — automated test · synthetic signals')
            self.recording = WindowRecording(self, output / 'PhysioViewerRT-live-test.mp4')
            recordings.append(self.recording)

        def closeEvent(self, event):
            self.recording.finish()
            super().closeEvent(event)

    integration.MainWindow = RecordedWindow
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(integration.LocalLSLIntegrationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'passed': result.wasSuccessful(), 'tests_run': result.testsRun,
              'failures': [message for _, message in result.failures],
              'errors': [message for _, message in result.errors],
              'capture': [{'frames': recording.frames, 'fps': recording.FPS,
                           'duration_seconds': recording.frames/recording.FPS,
                           'errors': recording.errors, 'timeline': recording.timeline}
                          for recording in recordings]}
    (output / 'test-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Recording:', output / 'PhysioViewerRT-live-test.mp4', flush=True)
    print('Report:', output / 'test-report.json', flush=True)
    return 0 if result.wasSuccessful() and not any(r.errors for r in recordings) else 1


if __name__ == '__main__':
    raise SystemExit(main())
