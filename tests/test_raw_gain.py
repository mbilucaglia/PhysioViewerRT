"""Amplitude changes retain the two existing batched visuals."""
import unittest
from physiolab.vispy_raw import VisPyRawPlot

class FakeBank:
    def __init__(self):
        self.gains = []
        self.rings = [object()]
    def set_gain(self, gain):
        self.gains.append(gain)

class FakeCanvas:
    def __init__(self): self.updates = 0
    def update(self): self.updates += 1

class GainTests(unittest.TestCase):
    def test_amplitude_change_retains_existing_layers(self):
        plot = VisPyRawPlot.__new__(VisPyRawPlot)
        plot.vertical_gain = 1.
        plot._banks = {'raw': FakeBank(), 'filtered': FakeBank()}
        plot.canvas = FakeCanvas()
        old = tuple(plot._banks.values())
        plot.set_vertical_gain(2.)
        self.assertEqual(tuple(plot._banks.values()), old)
        self.assertEqual([bank.gains for bank in old], [[2.], [2.]])
        self.assertEqual(plot.canvas.updates, 1)

    def test_invalid_gain_is_rejected(self):
        plot = VisPyRawPlot.__new__(VisPyRawPlot)
        plot.vertical_gain = 1.
        with self.assertRaises(ValueError): plot.set_vertical_gain(0.)

if __name__ == '__main__':
    unittest.main()
