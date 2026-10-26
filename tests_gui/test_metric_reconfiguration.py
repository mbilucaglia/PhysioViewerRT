"""Metric setting changes replay data without reallocating scene programs."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

import numpy as np
from PySide6.QtWidgets import QApplication
from physiolab.vispy_metrics import VisPyMetricPlot


class MetricReconfigurationTests(unittest.TestCase):
    def test_time_and_amplitude_rulers_track_view_without_replacing_programs(self):
        plot = self.plot
        plot.widget.resize(1000, 500)
        plot.widget.show()
        self.app.processEvents()
        programs = tuple(layer.visual.shared_program for layer in plot._layers[self.key])
        plot.set_amplitude_units('σ', 'Baseline standard deviations')
        plot.set_xrange(0., 10.)
        plot.set_series(self.key, [0., .5, 1.], [0., 3., 8.], [0., .5, 1.], [0., 3., 8.])
        self.app.processEvents()
        engine = plot.engine
        self.assertFalse(engine.amplitude_ruler.isHidden())
        self.assertEqual(engine.amplitude_ruler._unit, 'σ')
        self.assertEqual(engine.time_footer._unit, 's')
        low, high = engine.y_bounds
        bar = engine.amplitude_ruler.bar
        self.assertAlmostEqual(bar.value / bar.pixels,
                               (high-low)/engine.canvas.native.height())
        time_bar = engine.time_footer.bar
        self.assertAlmostEqual(time_bar.value/time_bar.pixels,
                               10./engine.canvas.native.width())
        plot.set_amplitude_units('norm.', 'Fixed baseline min–max span')
        self.assertEqual(engine.amplitude_ruler._unit, 'norm.')
        self.assertEqual(programs, tuple(layer.visual.shared_program
                                        for layer in plot._layers[self.key]))

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

    def test_shared_cursor_expires_points_from_a_series_that_stopped_updating(self):
        other = ('PPG','HR')
        plot = VisPyMetricPlot((self.key,other))
        try:
            plot.set_xrange(0.,1.)
            plot.set_series(self.key,[.01,.51],[1.,2.],[.01,.51],[1.,2.])
            dots = plot._layers[self.key][1]
            visual = dots.visual
            self.assertEqual(np.isfinite(dots.ring.stamps).sum(), 2)
            plot.set_series(other,[2.,2.5],[3.,4.],[2.,2.5],[3.,4.])
            plot.refresh_axes()
            self.assertFalse(np.isfinite(dots.ring.stamps).any())
            self.assertIs(dots.visual, visual)
            self.assertEqual(dots.expire_points(2.5), 0)
        finally:
            plot.close()

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
