"""Painted labels and physical rulers follow the public engine state."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

from PySide6.QtWidgets import QApplication, QLabel
from physiolab.vispy_plot_engine import VisPyPlotEngine


class TextResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_channel_growth_shrink_and_reset_update_the_painted_gutter(self):
        engine = VisPyPlotEngine()
        self.addCleanup(engine.close)
        gutter = engine.label_gutter
        for names in (['F3', 'F4'], [f'CH{i}' for i in range(64)], ['Cz']):
            engine.set_channel_labels(names)
            self.assertEqual(engine.channel_names, tuple(names))
            self.assertEqual(gutter.names, tuple(names))
            self.assertFalse(gutter.isHidden())
            self.assertIn(names[-1], gutter.toolTip())
            self.assertEqual(gutter.findChildren(QLabel), [])
        engine.set_channel_labels(())
        self.assertEqual(engine.channel_names, ())
        self.assertTrue(gutter.isHidden())
        engine.set_channel_labels(['Pz'])
        self.assertEqual(engine.channel_names, ('Pz',))
        self.assertFalse(gutter.isHidden())

    def test_dense_channel_gutter_preserves_baselines_without_overlap(self):
        engine = VisPyPlotEngine()
        self.addCleanup(engine.close)
        engine.set_channel_labels([f'CH{i + 1}' for i in range(32)])
        gutter = engine.label_gutter
        for height in (120, 350, 900):
            gutter.resize(48, height)
            gutter.update_density()
            centers = sorted(gutter.label_center(i) for i in gutter.visible_indices)
            self.assertGreater(len(centers), 1)
            for first, second in zip(centers, centers[1:]):
                self.assertGreaterEqual(second - first, gutter.fontMetrics().height() + gutter.LABEL_GAP)
            for index in gutter.visible_indices:
                expected = height * (1 - (6 * index + 3) / 195)
                self.assertAlmostEqual(gutter.label_center(index), expected)
            self.assertLess(gutter.minimumSizeHint().height(), 32 * gutter.fontMetrics().height())
        self.assertEqual(len(gutter.visible_indices), 32)
        self.assertIn('CH32', gutter.toolTip())

    def test_physical_rulers_track_duration_and_canvas_size(self):
        engine = VisPyPlotEngine()
        self.addCleanup(engine.close)
        engine.widget.resize(640, 350)
        engine.widget.show()
        self.app.processEvents()
        engine.set_view(0., 1., -2., 2.)
        engine.set_axis_labels(duration=10., bounds=(-2., 2.))
        engine.set_amplitude_range(120., 'µV')
        self.assertEqual(engine.time_duration, 10.)
        self.assertEqual(engine.y_bounds, (-2., 2.))
        self.assertIsNotNone(engine.time_footer.bar)
        self.assertIsNotNone(engine.amplitude_ruler.bar)
        time_bar = engine.time_footer.bar
        amplitude_bar = engine.amplitude_ruler.bar
        self.assertAlmostEqual(time_bar.value / time_bar.pixels,
                               10. / engine.canvas.native.width())
        self.assertAlmostEqual(amplitude_bar.value / amplitude_bar.pixels,
                               120. / engine.canvas.native.height())
        self.assertTrue(time_bar.label.endswith(' s'))
        self.assertTrue(amplitude_bar.label.endswith('µV'))

    def test_optional_vispy_axes_remain_linked_to_view(self):
        engine = VisPyPlotEngine(show_axes=True)
        self.addCleanup(engine.close)
        self.assertIsNotNone(engine.xaxis)
        self.assertIsNotNone(engine.yaxis)
        engine.set_view(0., 1., -2., 2.)
        self.assertEqual(engine.y_bounds, (-2., 2.))


if __name__ == '__main__':
    unittest.main()
