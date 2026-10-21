"""Windows Qt smoke checks for stream selector and raw/metric UI boundaries.

Run with QT_QPA_PLATFORM=offscreen and the full requirements installed.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import time
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtWidgets import QApplication

from physiolab.gui import MainWindow
from physiolab.ingress import ChunkMailbox


class FakeInfo:
    def __init__(self, uid, channels=1):
        self.identifier, self.channels = uid, channels

    def uid(self):
        return self.identifier

    def channel_count(self):
        return self.channels

    def nominal_srate(self):
        return 32.

    def name(self):
        return 'Synthetic'

    def type(self):
        return 'EDA'


class FakeReceiver:
    def __init__(self, fs):
        self.mailbox = ChunkMailbox(fs)
        self.active = True

    def stop(self):
        self.active = False
        return True


class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Startup discovery is asynchronous and tested independently.
        with patch.object(MainWindow, 'refresh', lambda window: None):
            self.window = MainWindow()
        self.window.resize(1100, 660)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_raw_ingress_and_metrics_can_update_together(self):
        n = 256
        stamps = 100. + np.arange(n) / 256.
        samples = np.column_stack([
            np.sin(2*np.pi*10*(stamps-100.) + i)
            for i in range(8)
        ])
        worker = FakeReceiver(256.)
        names = ['F3', 'F4', 'O1', 'O2', 'P3', 'P4', 'C3', 'C4']
        worker.mailbox.put((
            samples, samples*.8, names,
            {'IAF': 10., 'AWI': .2, 'BAR': 1.4},
            256., stamps, time.monotonic()
        ))
        self.window.workers['EEG'] = worker
        self.window.poll_receivers()
        self.assertEqual(len(self.window.raw_history['EEG']), 1)
        self.assertEqual(self.window.latest_metrics['EEG']['BAR'], 1.4)
        self.assertIn('0.200', self.window.metric_labels[('EEG', 'AWI')].text())
        self.window.render_frame()
        self.window.tabs.setCurrentIndex(1)
        self.window.render_frame()
        self.assertEqual(self.window.metric_history[('EEG', 'AWI')][-1][1], .2)

    def test_changing_lsl_source_never_waits_for_metadata(self):
        def slow_lookup(info, timeout):
            time.sleep(.3)
            return ['EDA'], ''
        combo = self.window.selectors['EDA']
        with patch('physiolab.lsl_tasks.full_channel_labels', slow_lookup):
            started = time.perf_counter()
            combo.addItem('Synthetic EDA', FakeInfo('synthetic-eda'))
            elapsed = time.perf_counter()-started
            self.assertLess(elapsed, .15)
            self.assertFalse(self.window.stream_buttons['EDA'].isEnabled())
            deadline = time.monotonic()+2.
            while time.monotonic() < deadline:
                self.app.processEvents()
                if self.window.channel_selectors['EDA'].names == ['EDA']:
                    break
                time.sleep(.02)
            self.assertEqual(self.window.channel_selectors['EDA'].names, ['EDA'])
            self.assertTrue(self.window.stream_buttons['EDA'].isEnabled())

    def test_raw_scroll_event_does_not_force_synchronous_plotting(self):
        self.window.raw_view_scrolled()
        self.assertGreater(self.window.raw_interacting_until, time.monotonic())
        self.window.render_frame()
        self.assertTrue(self.window.raw_dirty)
        bar = self.window.raw_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
