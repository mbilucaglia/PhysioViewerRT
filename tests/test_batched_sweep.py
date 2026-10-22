"""Standard VisPy batch geometry and redraw tests without an OpenGL context."""
import unittest
from unittest.mock import patch
import numpy as np
from physiolab.batched_sweep import BatchedSweepBank, sweep_positions


class FakeLine:
    def __init__(self, **kwargs):
        self.pos = kwargs['pos']
        self.calls = 0
        self.visible = True
        self.parent = kwargs['parent']

    def set_data(self, **kwargs):
        self.pos = kwargs['pos']
        self.calls += 1


class BatchTests(unittest.TestCase):
    def test_single_line_per_bank_and_no_redraw_for_duplicate_data(self):
        with patch('physiolab.batched_sweep._line_class', return_value=FakeLine):
            bank = BatchedSweepBank(None, 32, 5., 100., '#000000')
            self.assertEqual(bank.capacity, 500)
            self.assertEqual(bank.visual.pos.shape, (32 * 500 * 2, 2))
            t = np.arange(100, dtype=float) / 100
            x = np.tile(np.linspace(.1, .2, 100)[:, None], (1, 32))
            self.assertGreater(bank.append(t, x), 0)
            self.assertEqual(bank.visual.calls, 1)
            self.assertEqual(bank.append(t, x), 0)
            self.assertEqual(bank.visual.calls, 1)
            bank.set_gain(2.)
            self.assertEqual(bank.visual.calls, 2)

    def test_channel_geometry_remains_disconnected(self):
        with patch('vispy.scene.visuals.Line', FakeLine):
            bank = BatchedSweepBank(None, 2, 5., 10., '#000000')
            t = np.arange(10, dtype=float) / 10
            bank.append(t, np.zeros((10, 2)))
            pos = bank.visual.pos
            self.assertEqual(pos.shape, (2 * bank.capacity * 2, 2))
            self.assertTrue(np.all(pos[:2 * bank.capacity, 1] <= 1.))
            self.assertTrue(np.all(pos[2 * bank.capacity:, 1] >= -10.))
            self.assertEqual(sweep_positions([]).shape, (0, 2))


if __name__ == '__main__':
    unittest.main()
