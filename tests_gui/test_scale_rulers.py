"""Physical ruler lengths must track canvas transforms without quantization."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from physiolab.scale_rulers import ScaleRuler, scale_bar


class ScaleRulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_exact_physical_length_at_several_scales(self):
        for units_per_pixel in (.003, .04, .7, 3.5, 700.):
            bar = scale_bar(units_per_pixel, 'µV', 100)
            self.assertAlmostEqual(bar.value, bar.pixels * units_per_pixel)
            self.assertLessEqual(bar.pixels, 80)
            self.assertGreaterEqual(bar.pixels, 32)
            self.assertTrue(bar.label.endswith('µV'))

    def test_resized_space_limits_bracket(self):
        bar = scale_bar(.01, 's', 19)
        self.assertEqual(bar.value, .1)
        self.assertEqual(bar.pixels, 10)

    def test_vertical_label_reserves_space_for_number_and_unit(self):
        ruler = ScaleRuler(Qt.Orientation.Vertical)
        ruler.resize(90, 180)
        ruler.show()
        self.addCleanup(ruler.close)
        self.app.processEvents()
        for unit in ('µS', '', 'custom source unit'):
            ruler.set_scale(.0000005, unit)
            self.assertIn(' ', ruler.bar.label)
            self.assertTrue(ruler.bar.label.endswith(unit or 'a.u.'))
            self.assertLessEqual(ruler.fontMetrics().horizontalAdvance(ruler.bar.label),
                                 ruler.width() - 24)
            ruler.grab()

    def test_unavailable_scales_hide_bracket(self):
        for invalid in (0, -1, float('nan'), float('inf')):
            self.assertIsNone(scale_bar(invalid, 's', 80))
        self.assertIsNone(scale_bar(1, 's', 0))

    def test_qt_resize_and_gain_update_geometry(self):
        ruler = ScaleRuler(Qt.Orientation.Vertical)
        ruler.resize(90, 180)
        ruler.show()
        self.app.processEvents()
        ruler.set_scale(.5, 'µV')
        self.assertEqual(ruler.bar.value, 20)
        self.assertEqual(ruler.bar.pixels, 40)
        ruler.set_scale(.25, 'µV')
        self.assertEqual(ruler.bar.value, 20)
        self.assertEqual(ruler.bar.pixels, 80)
        ruler.resize(90, 50)
        self.app.processEvents()
        self.assertLessEqual(ruler.bar.pixels, 34)
        ruler.grab()  # Exercise native QPainter bracket and label rendering.
        ruler.close()


if __name__ == '__main__':
    unittest.main()
