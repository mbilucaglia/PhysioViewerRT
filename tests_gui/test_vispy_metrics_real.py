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
            self.assertEqual(plot.labels[0].text, 'F3')
            self.assertEqual(plot.labels[1].text, 'F4')
        finally:
            plot.close()


if __name__ == '__main__':
    unittest.main()
