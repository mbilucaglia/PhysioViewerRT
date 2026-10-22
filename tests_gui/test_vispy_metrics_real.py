"""Construct the real VisPy Metrics canvas in offscreen Qt.

Unlike the mock backend-switch tests, this catches API mismatches in
AxisWidget, ViewBox, GridLines, Line and Markers at initialization time.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

import numpy as np
from PySide6.QtWidgets import QApplication
from physiolab.vispy_metrics import VisPyMetricPlot
from physiolab.vispy_raw import VisPyRawPlot
from physiolab.vispy_plot_engine import VisPyPlotEngine


class RealVisPyMetricsConstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_create_real_canvas_axes_and_update_metric_series(self):
        keys = (('EEG', 'AWI'), ('EEG', 'BAR'), ('EDA', 'SCL'),
                ('PPG', 'HR'), ('EI', 'EI'))
        plot = VisPyMetricPlot(keys)
        try:
            self.assertIsNotNone(plot.widget)
            self.assertEqual(len(plot.lines), 5)
            self.assertEqual(len(plot.points), 5)
            self.assertIsInstance(plot.engine, VisPyPlotEngine)
            self.assertEqual(plot.engine.canvas.bgcolor.hex, '#ffffff')
            plot.set_xrange(0., 5.)
            plot.set_series(
                keys[0], np.array([0., 1., np.nan, 4.]),
                np.array([1., 2., np.nan, 3.]),
                np.array([0., 1., 4.]), np.array([1., 2., 3.]),
            )
            plot.refresh_axes()
            self.assertTrue(plot.lines[keys[0]].visible)
            self.assertTrue(plot.points[keys[0]].visible)
        finally:
            plot.close()

    def test_raw_blue_cursor_never_leads_real_samples(self):
        plot = VisPyRawPlot('EEG')
        try:
            samples = np.array([5., 5.1, 5.2, 5.3])
            data = np.sin(samples)[:, None]
            frame = (samples, data, data, None, None, ('F3',))
            # Simulate viewport clock running 80 ms ahead of acquisition.
            plot.set_frame(frame, 0., 5., sweep_head=5.38)
            np.testing.assert_allclose(
                plot.engine.sweep_cursor._pos[:, 0], [.06, .06], atol=1e-5
            )
        finally:
            plot.close()

    def test_raw_uses_same_engine_with_labels_and_gain(self):
        plot = VisPyRawPlot('EEG')
        try:
            self.assertIsInstance(plot.engine, VisPyPlotEngine)
            self.assertEqual(plot.engine.canvas.bgcolor.hex, '#ffffff')
            plot.set_vertical_gain(2.)
            self.assertEqual(plot.vertical_gain, 2.)
            samples = np.array([0., .1, .2, .3])
            data = np.column_stack((np.sin(samples), 6.+np.cos(samples)))
            frame = (samples, data, data*.5, None, None, ('F3', 'F4'))
            plot.set_frame(frame, 0., 5., sweep_head=.3)
            self.assertTrue(plot.raw_line.visible)
            self.assertEqual(
                tuple(label.text for label in plot.engine._channel_labels[:2]),
                ('F3', 'F4')
            )
            self.assertIs(plot.engine.widget, plot.engine.canvas.native)
            self.assertEqual(plot.engine._axis_duration, 5.)
        finally:
            plot.close()


    def test_both_adapters_preserve_historical_gpu_segments(self):
        """Appending a sample must not rewrite previous sweep positions."""
        raw = VisPyRawPlot('EEG')
        metrics = VisPyMetricPlot((('EEG', 'AWI'),))
        try:
            times = np.arange(.05, 1.05, .05)
            data = np.sin(times)[:, None]
            raw.set_frame((times, data, data*.5, None, None, ('F3',)),
                          0., 5.)
            layer = raw.layers['raw'][0]
            old = layer.ring.positions.copy()
            old_visual = raw.raw_line
            more = np.append(times, [1.05, 1.10])
            new_data = np.sin(more)[:, None]
            raw.set_frame((more, new_data, new_data*.5, None, None, ('F3',)),
                          0., 5.)
            self.assertIs(raw.raw_line, old_visual)
            np.testing.assert_array_equal(
                old[2:18], layer.ring.positions[2:18])
            key = ('EEG', 'AWI')
            metrics.set_xrange(0., 5.)
            metrics.set_series(key, times, np.sin(times),
                               times[::10], np.sin(times[::10]))
            metric_layer = metrics._layers[key][0]
            previous = metric_layer.ring.positions.copy()
            metric_visual = metrics.lines[key]
            metrics.set_series(key, more, np.sin(more),
                               more[::10], np.sin(more[::10]))
            self.assertIs(metrics.lines[key], metric_visual)
            np.testing.assert_array_equal(
                previous[2:18], metric_layer.ring.positions[2:18])
        finally:
            raw.close()
            metrics.close()

    def test_metrics_cursor_uses_real_measured_sample(self):
        key = ('EEG', 'AWI')
        plot = VisPyMetricPlot((key,))
        try:
            plot.set_xrange(0., 5.)
            timestamps = np.array([0., .5, 1.])
            plot.set_series(key, timestamps, [1., 2., 3.],
                            timestamps, [1., 2., 3.])
            plot.set_xrange(-3., 2.)
            # Viewport clock is 2s; real metrics end at 1s.
            np.testing.assert_allclose(
                plot.engine.sweep_cursor._pos[:, 0], [.2, .2], atol=1e-6)
        finally:
            plot.close()


if __name__ == '__main__':
    unittest.main()
