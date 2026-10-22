"""GPU sweep allocations are bounded per GUI frame."""
import unittest
from unittest.mock import patch
from physiolab.vispy_raw import VisPyRawPlot


class FakeVisual:
    pass


class FakeLayer:
    created = 0

    def __init__(self, parent, duration, rate, color):
        FakeLayer.created += 1
        self.visual = FakeVisual()

    def set_gain(self, gain, center):
        pass

    def close(self):
        pass


class ProgressiveLayerTests(unittest.TestCase):
    def test_many_channels_allocate_only_four_pairs_per_frame(self):
        FakeLayer.created = 0
        plot = VisPyRawPlot.__new__(VisPyRawPlot)
        plot.view = type('View', (), {'scene': object()})()
        plot.layers = {'raw': [], 'filtered': []}
        plot._configuration = None
        plot._target_channels = 0
        plot._latest = float('-inf')
        plot.vertical_gain = 1.
        plot.raw_line = plot.filtered_line = None
        with patch('physiolab.incremental_sweep.IncrementalSweepLayer', FakeLayer):
            plot._ensure_layers(32, 5., 100.)
            self.assertEqual(FakeLayer.created, 8)
            self.assertEqual(len(plot.layers['raw']), 4)
            for _ in range(7):
                plot._ensure_layers(32, 5., 100.)
            self.assertEqual(len(plot.layers['raw']), 32)
            self.assertEqual(FakeLayer.created, 64)
            plot._ensure_layers(32, 5., 100.)
            self.assertEqual(FakeLayer.created, 64)
            plot._ensure_layers(32, 10., 50.)
            self.assertEqual(FakeLayer.created, 72)
            self.assertEqual(len(plot.layers['raw']), 4)


if __name__ == '__main__':
    unittest.main()
