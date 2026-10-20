"""Regression checks for 50/100 Hz causal mains-notch processing."""
import unittest

import numpy as np
from scipy.signal import sosfreqz

from physiolab.processing import Processor


class NotchFilterTests(unittest.TestCase):
    def test_notches_are_enabled_only_below_nyquist(self):
        cases = [
            (32, []), (100, []), (128, [50.0]),
            (200, [50.0]), (256, [50.0, 100.0]),
        ]
        for fs, expected in cases:
            with self.subTest(fs=fs):
                proc = Processor('EDA', fs, 1, ['EDA'])
                self.assertEqual(proc.notch_frequencies, expected)

    def test_notch_rejects_mains_harmonics(self):
        proc = Processor('EDA', 256, 1, ['EDA'])
        for freq in (50.0, 100.0):
            _, response = sosfreqz(proc.sos, worN=[freq], fs=256)
            self.assertLess(float(np.abs(response[0])), 0.01)

    def test_filtered_data_stays_finite_across_chunks(self):
        fs = 256
        t = np.arange(fs * 4) / fs
        wave = (2 + 0.1*np.sin(2*np.pi*2*t)
                + np.sin(2*np.pi*50*t) + np.sin(2*np.pi*100*t))
        proc = Processor('EDA', fs, 1, ['EDA'])
        for start in range(0, len(wave), 15):
            proc.push(wave[start:start+15, None])
        self.assertTrue(np.isfinite(proc.filtered).all())
        self.assertEqual(proc.filtered.shape[1], 1)


if __name__ == '__main__':
    unittest.main()
