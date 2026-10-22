"""Regression tests for background raw waveform preparation (without Qt)."""
import unittest

import numpy as np

from physiolab.raw_render import prepare_raw_window


class RawRenderTests(unittest.TestCase):
    @staticmethod
    def chunks(fs=256, seconds=8, channels=32):
        chunks = []
        for i in range(seconds * 10):
            size = round(fs / 10)
            stamps = 100. + (i * size + np.arange(size)) / fs
            raw = np.sin(stamps[:, None] * 10 + np.arange(channels))
            filtered = raw * .5
            chunks.append((stamps, raw, filtered,
                           [f'C{ch}' for ch in range(channels)], float(fs)))
        return tuple(chunks)

    def test_viewport_crops_and_bounds_output(self):
        history = self.chunks(seconds=30)
        result = prepare_raw_window(history, left=26., right=30.,
                                    origin=100., max_points=400)
        self.assertIsNotNone(result)
        timestamps, raw, processed, centers, scales, labels = result
        self.assertLessEqual(len(timestamps), 400)
        self.assertEqual(raw.shape, processed.shape)
        self.assertEqual(raw.shape[1], 8)
        self.assertEqual(len(labels), 8)
        self.assertTrue(np.all(np.diff(timestamps) > 0))
        self.assertGreaterEqual(timestamps[0], 26.)
        self.assertLessEqual(timestamps[-1], 30.)
        self.assertTrue(np.isfinite(raw).all())
        self.assertTrue(np.isfinite(processed).all())

    def test_fixed_reference_is_reused(self):
        history = self.chunks(seconds=8)
        original = prepare_raw_window(history, 1., 4., 100.)
        centers, scales = original[3:5]
        again = prepare_raw_window(history, 2., 5., 100.,
                                   reference=(centers, scales))
        self.assertIs(again[3], centers)
        self.assertIs(again[4], scales)
        np.testing.assert_allclose(again[1][0], (
            (np.sin((again[0][0] + 100.) * 10 + np.arange(8))
             - centers) / scales + np.arange(8) * 6
        ), atol=1e-10)

    def test_missing_window_and_insufficient_startup_samples(self):
        history = self.chunks(seconds=2)
        self.assertIsNone(prepare_raw_window(history, 10., 11., 100.))
        early = prepare_raw_window(history, 0., .1, 100.)
        self.assertIsNotNone(early)
        self.assertGreaterEqual(len(early[0]), 2)
        self.assertTrue(np.isfinite(early[1]).all())

    def test_first_short_chunk_visible_even_without_decimation_grid_points(self):
        fs = 512.
        stamps = 100. + np.array([1., 2., 3., 4.]) / fs
        values = np.array([[0.], [0.1], [0.2], [0.3]])
        history = ((stamps, values, values.copy(), ['C0'], fs),)
        frame = prepare_raw_window(history, 0., .02, 100.,
                                   max_points=10, decimation_span=20.)
        self.assertIsNotNone(frame)
        self.assertEqual(len(frame[0]), 4)
        self.assertTrue(np.isfinite(frame[1]).all())

    def test_channel_limit_applied_before_preparation(self):
        history = self.chunks(seconds=4, channels=32)
        result = prepare_raw_window(
            history, 1., 3., 100., max_channels=4)
        self.assertEqual(result[1].shape[1], 4)
        self.assertEqual(len(result[-1]), 4)

    def test_invalid_budgets_rejected(self):
        history = self.chunks(seconds=2)
        with self.assertRaises(ValueError):
            prepare_raw_window(history, 0., 1., 100., max_channels=0)
        with self.assertRaises(ValueError):
            prepare_raw_window(history, 0., 1., 100., max_points=0)

    def test_invalid_reference_is_rejected(self):
        history = self.chunks(seconds=3)
        with self.assertRaises(ValueError):
            prepare_raw_window(history, 1., 2., 100.,
                               reference=(np.zeros(4), np.ones(4)))


if __name__ == '__main__':
    unittest.main()
