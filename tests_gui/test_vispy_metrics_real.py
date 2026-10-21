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


if __name__ == '__main__':
    unittest.main()
