"""Metric setting changes replay data without reallocating scene programs."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

import numpy as np
from PySide6.QtWidgets import QApplication
from physiolab.vispy_metrics import VisPyMetricPlot


class MetricReconfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.key = ('EEG', 'AWI')
        self.plot = VisPyMetricPlot((self.key,))
        self.addCleanup(self.plot.close)

    def feed(self, times, **kwargs):
        times = np.asarray(times)
        self.plot.set_series(self.key, times, times + 1,
                             times, times + 1, **kwargs)

    def test_initial_signature_does_not_replace_empty_layers(self):
        pair = self.plot._layers[self.key]
        rings = tuple(layer.ring for layer in pair)
        self.plot.set_presentation_signature(('none', 'pchip'))
        self.assertEqual(tuple(layer.ring for layer in pair), rings)

    def test_duration_and_transform_changes_preserve_visuals_and_replay(self):
        self.plot.set_presentation_signature(('none', 'pchip'))
        pair = self.plot._layers[self.key]
        visuals = tuple(layer.visual for layer in pair)
        programs = tuple(visual.shared_program for visual in visuals)
        self.feed([0., .5, 1.])
        self.plot.set_xrange(0., 10.)
        self.assertTrue(all(layer.visual is visual
                            for layer, visual in zip(pair, visuals)))
        self.assertTrue(all(layer.visual.shared_program is program
                            for layer, program in zip(pair, programs)))
        self.assertTrue(all(layer.visual.visible for layer in pair))
        self.feed([0., .5, 1.])
        self.assertTrue(all(layer.ring.last_time == 1. for layer in pair))
        self.plot.set_presentation_signature(('ema', 'pchip'))
        self.assertTrue(all(layer.visual is visual
                            for layer, visual in zip(pair, visuals)))
        self.assertTrue(all(not np.isfinite(layer.ring.last_time) for layer in pair))
        self.feed([0., .5, 1.])
        self.assertTrue(all(layer.ring.last_time == 1. for layer in pair))

    def test_reenabled_hidden_series_replays_missing_history_in_place(self):
        pair = self.plot._layers[self.key]
        visuals = tuple(layer.visual for layer in pair)
        self.feed([0., .5])
        self.feed([0., .5, 1.], visible=False)
        self.assertTrue(all(not layer.visual.visible for layer in pair))
        self.feed([0., .5, 1., 1.5], show_markers=False)
        self.assertTrue(pair[0].visual.visible)
        self.assertFalse(pair[1].visual.visible)
        self.assertEqual(pair[0].ring.last_time, 1.5)
        self.feed([0., .5, 1., 1.5, 2.])
        self.assertTrue(all(layer.ring.last_time == 2. for layer in pair))
        self.assertTrue(all(layer.visual is visual
                            for layer, visual in zip(pair, visuals)))


if __name__ == '__main__':
    unittest.main()
