import unittest
import numpy as np
from physiolab.amplitude_display import visible_gain


class AutoscaleTests(unittest.TestCase):
    def test_common_gain_preserves_eeg_ratios_and_fits_both_layers(self):
        raw = np.array([[-2., -2.], [2., 14.]])
        frame = (np.array([0., 1.]), raw, raw.copy())
        gain = visible_gain(frame, 5.)
        self.assertEqual(gain, 2.5/8.)
        self.assertTrue(np.all(np.abs((raw-[0., 6.])*gain) <= 2.5))

    def test_only_visible_window_and_enabled_layers_set_gain(self):
        times = np.array([0., 4., 5.])
        raw = np.array([[100.], [1.], [-1.]])
        filtered = raw * 10
        self.assertEqual(visible_gain((times, raw, filtered), 2., show_filtered=False), 2.5)
        self.assertEqual(visible_gain((times, raw, filtered), 2.), .25)
        self.assertEqual(visible_gain((times, raw, filtered), 5., show_filtered=False), .025)

    def test_flat_or_hidden_data_does_not_produce_infinite_gain(self):
        x = np.zeros((3, 1))
        frame = (np.arange(3), x, x)
        self.assertIsNone(visible_gain(frame, 5.))
        self.assertIsNone(visible_gain(frame, 5., False, False))
