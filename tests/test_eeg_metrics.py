"""Synthetic checks for EEG AWI/BAR 1-second metrics."""
import unittest
import numpy as np
from physiolab.processing import Processor


class EEGMetricTests(unittest.TestCase):
    def test_awi_and_bar(self):
        fs = 256
        t = np.arange(fs * 3) / fs
        # Larger left alpha => negative AWI; beta rhythm in all channels.
        data = np.column_stack([
            3.0*np.sin(2*np.pi*10*t) + 1*np.sin(2*np.pi*20*t),
            1.5*np.sin(2*np.pi*10*t) + 1*np.sin(2*np.pi*20*t),
            2.0*np.sin(2*np.pi*10*t) + 1*np.sin(2*np.pi*20*t),
        ])
        processor = Processor('EEG', fs, 3, ['F3', 'F4', 'O1'])
        result = None
        for start in range(0, len(data), fs // 2):
            result = processor.push(data[start:start + fs // 2]) or result
        self.assertIsNotNone(result)
        self.assertLess(result['AWI'], 0)
        self.assertGreater(result['BAR'], 0)
        self.assertLess(result['BAR'], 1)
        self.assertEqual(result['IAF'], 10)

    def test_bar_without_frontal_labels(self):
        fs = 256
        t = np.arange(fs * 2) / fs
        data = np.column_stack([
            np.sin(2*np.pi*10*t) + .4*np.sin(2*np.pi*20*t),
            np.sin(2*np.pi*11*t) + .4*np.sin(2*np.pi*19*t)
        ])
        proc = Processor('EEG', fs, 2, ['O1', 'O2'])
        result = None
        for start in range(0, len(data), fs//2):
            result = proc.push(data[start:start+fs//2]) or result
        self.assertIsNotNone(result['BAR'])
        self.assertIsNone(result['AWI'])


if __name__ == '__main__':
    unittest.main()
