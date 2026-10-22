"""Batched display buffer invariants; no OpenGL context required."""
import unittest
from unittest.mock import patch
import numpy as np
from physiolab.batched_sweep import BatchedSweepBank


class FakeVisual:
    def __init__(self):
        self.visible = True
        self.writes = []
        self.gain = 1.0
        self.parent = object()

    def patch(self, first, data):
        self.writes.append((first, np.array(data, copy=True)))

    def set_gain(self, gain):
        self.gain = gain


class FakeVisualClass:
    instances = []

    def __init__(self, capacity, color, parent):
        self.capacity = capacity
        self.obj = FakeVisual()
        self.instances.append(self.obj)

    def __getattr__(self, name):
        return getattr(self.obj, name)


class BatchTests(unittest.TestCase):
    def test_one_visual_for_many_channels(self):
        FakeVisualClass.instances.clear()
        with patch('physiolab.batched_sweep._batch_visual',
                   return_value=FakeVisualClass):
            bank = BatchedSweepBank(None, 32, 5., 100., '#000000')
            self.assertEqual(len(FakeVisualClass.instances), 1)
            self.assertEqual(bank.visual.capacity, 32 * 500)
            t = np.arange(100) / 100.
            x = np.tile(np.linspace(0.1, 0.2, 100)[:, None], (1, 32))
            self.assertGreater(bank.append(t, x), 0)
            self.assertLessEqual(len(bank.visual.writes), 64)
            self.assertEqual(bank.last_time, t[-1])
            count = len(bank.visual.writes)
            self.assertEqual(bank.append(t, x), 0)
            self.assertEqual(len(bank.visual.writes), count)
            bank.set_gain(2.)
            self.assertEqual(bank.visual.gain, 2.)

    def test_channel_geometry_is_disconnected_in_gpu_buffer(self):
        with patch('physiolab.batched_sweep._batch_visual',
                   return_value=FakeVisualClass):
            bank = BatchedSweepBank(None, 2, 5., 10., '#000000')
            t = np.arange(10) / 10.
            x = np.zeros((10, 2))
            bank.append(t, x)
            self.assertTrue(any(offset >= 2 * bank.capacity
                                for offset, _ in bank.visual.writes))
            for _, data in bank.visual.writes:
                self.assertEqual(data.shape[1], 3)


if __name__ == '__main__':
    unittest.main()
