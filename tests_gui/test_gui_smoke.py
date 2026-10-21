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

    def test_switch_raw_renderer_without_changing_metrics_or_receivers(self):
        from PySide6.QtWidgets import QWidget

        class FakeGpuPlot:
            def __init__(self, kind):
                self.widget = QWidget()
                self.frames = []

            def set_frame(self, frame, left, right, **options):
                self.frames.append((left, right, options))

            def reset(self):
                pass

            def close(self):
                pass

        old_metrics = self.window.metric_history
        old_receivers = self.window.workers
        with patch('physiolab.gui.VisPyRawPlot', FakeGpuPlot):
            self.window.raw_renderer_choice.setCurrentIndex(1)
            self.assertEqual(self.window.raw_renderer_mode, 'vispy')
            self.assertEqual(len(self.window.raw_vispy_plots), 3)
            for stack in self.window.raw_plot_stacks.values():
                self.assertEqual(stack.currentIndex(), 1)
            self.window.raw_renderer_choice.setCurrentIndex(0)
            self.assertEqual(self.window.raw_renderer_mode, 'pyqtgraph')
            for stack in self.window.raw_plot_stacks.values():
                self.assertEqual(stack.currentIndex(), 0)
        self.assertIs(self.window.metric_history, old_metrics)
        self.assertIs(self.window.workers, old_receivers)

    def test_metric_gpu_backend_preserves_values_controls_and_fallback(self):
        from PySide6.QtWidgets import QWidget

        class FakeMetricGpu:
            def __init__(self, keys):
                self.widget = QWidget()
                self.data = {}
                self.bounds = None
                self.keys = keys

            def set_series(self, key, x, y, mx, my, **options):
                self.data[key] = (np.asarray(x), np.asarray(y),
                                  np.asarray(mx), np.asarray(my), options)

            def set_xrange(self, left, right):
                self.bounds = (left, right)

            def refresh_axes(self):
                pass

            def close(self):
                pass

        original_history = self.window.metric_history
        key = ('EEG', 'AWI')
        current = time.monotonic()
        self.window.metric_history[key].extend([
            (current - 1., .2), (current - .5, .4), (current, .6)
        ])
        with patch('physiolab.gui.VisPyMetricPlot', FakeMetricGpu):
            self.window.metric_renderer_choice.setCurrentIndex(1)
            self.assertEqual(self.window.metric_renderer_mode, 'vispy')
            self.assertEqual(self.window.metric_plot_stack.currentIndex(), 1)
            self.window.refresh_metric_plot()
            gpu = self.window.vispy_metric_plot
            self.assertEqual(len(gpu.data[key][2]), 3)
            self.window.metric_checks[key].setChecked(False)
            self.assertFalse(gpu.data[key][4]['visible'])
            self.window.metric_checks[key].setChecked(True)
            self.window.zoom_metric_plot(.5)
            self.assertIsNotNone(gpu.bounds)
            self.window.metric_renderer_choice.setCurrentIndex(0)
            self.assertEqual(self.window.metric_plot_stack.currentIndex(), 0)
            self.assertIs(self.window.metric_history, original_history)
            self.assertAlmostEqual(self.window.metric_history[key][-1][1], .6)

    def test_mockup_tabs_sources_and_resizable_raw_panels(self):
        from PySide6.QtWidgets import QSplitter, QDoubleSpinBox
        self.assertEqual(
            [self.window.tabs.tabText(i) for i in range(self.window.tabs.count())],
            ['Raw Data', 'Metrics', 'Sources']
        )
        self.assertIsInstance(self.window.raw_plot_splitter, QSplitter)
        self.assertEqual(self.window.raw_plot_splitter.count(), 3)
        self.assertEqual(
            self.window.raw_scroll.verticalScrollBarPolicy(),
            __import__('PySide6.QtCore', fromlist=['Qt']).Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.window.tabs.setCurrentIndex(2)
        self.assertTrue(self.window.selectors['EEG'].isVisible())
        original_workers = self.window.workers
        self.window.tabs.setCurrentIndex(0)
        gain = self.window.raw_vertical_gains['EEG']
        self.assertIsInstance(gain, QDoubleSpinBox)
        self.assertEqual(gain.value(), 1.)
        self.window.adjust_raw_vertical_gain('EEG', 1.2)
        self.assertAlmostEqual(gain.value(), 1.2)
        self.assertEqual(self.window.raw_vertical_gains['EDA'].value(), 1.)
        self.assertIs(self.window.workers, original_workers)
        self.window.raw_time_window.setCurrentIndex(
            self.window.raw_time_window.findData(8)
        )
        self.assertEqual(self.window.raw_view_seconds, 8.)

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
