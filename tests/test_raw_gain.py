"""Amplitude changes must not discard existing GPU sweep history."""
import unittest
from physiolab.vispy_raw import VisPyRawPlot


class FakeLayer:
    def __init__(self):
        self.gains = []
        self.ring = object()

    def set_gain(self, gain, center):
        self.gains.append((gain, center))


class FakeCanvas:
    def __init__(self):
        self.updates = 0

    def update(self):
        self.updates += 1


class GainTests(unittest.TestCase):
    def test_amplitude_change_retains_existing_layers(self):
        plot = VisPyRawPlot.__new__(VisPyRawPlot)
        plot.vertical_gain = 1.
        plot.layers = {'raw': [FakeLayer() for _ in range(8)],
                       'filtered': [FakeLayer() for _ in range(8)]}
        plot.canvas = FakeCanvas()
        previous = tuple(plot.layers['raw'] + plot.layers['filtered'])
        plot.set_vertical_gain(2.)
        self.assertEqual(plot.vertical_gain, 2.)
        self.assertEqual(previous, tuple(plot.layers['raw'] + plot.layers['filtered']))
        self.assertEqual(plot.canvas.updates, 1)
        self.assertEqual(plot.layers['raw'][0].gains[-1][0], 2.)
        self.assertEqual(plot.layers['filtered'][7].gains[-1][0], 2.)

    def test_invalid_gain_is_rejected(self):
        plot = VisPyRawPlot.__new__(VisPyRawPlot)
        plot.vertical_gain = 1.
        with self.assertRaises(ValueError):
            plot.set_vertical_gain(0.)


if __name__ == '__main__':
    unittest.main()
