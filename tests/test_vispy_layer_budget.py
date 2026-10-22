"""Batched RAW rendering creates one visual per signal modality."""
import unittest
from unittest.mock import patch
from physiolab.vispy_raw import VisPyRawPlot


class FakeVisual:
    visible = True


class FakeBank:
    created = 0

    def __init__(self, parent, channels, duration, rate, color):
        FakeBank.created += 1
        self.visual = FakeVisual()
        self.channels = channels
        self.rings = []

    def set_gain(self, gain):
        pass

    def close(self):
        pass


class BatchedAllocationTests(unittest.TestCase):
    def test_many_channels_create_only_two_banks(self):
        FakeBank.created = 0
        plot = VisPyRawPlot.__new__(VisPyRawPlot)
        plot.view = type('View', (), {'scene': object()})()
        plot.layers = {'raw': [], 'filtered': []}
        plot._banks = {}
        plot._configuration = None
        plot._target_channels = 0
        plot._latest = float('-inf')
        plot.vertical_gain = 1.
        plot.raw_line = plot.filtered_line = None
        with patch('physiolab.batched_sweep.BatchedSweepBank', FakeBank):
            plot._ensure_layers(32, 5., 100.)
            self.assertEqual(FakeBank.created, 2)
            self.assertEqual(len(plot._banks), 2)
            plot._ensure_layers(32, 5., 100.)
            self.assertEqual(FakeBank.created, 2)
            plot._ensure_layers(32, 10., 50.)
            self.assertEqual(FakeBank.created, 4)
            self.assertEqual(len(plot._banks), 2)


if __name__ == '__main__':
    unittest.main()
