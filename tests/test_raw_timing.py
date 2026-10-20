"""Regression tests for monotonic raw waveform time axes."""
import unittest
import numpy as np
from physiolab.raw_timing import clean_lsl_chunk, visible_chunk, SmoothViewportClock


class RawTimingTests(unittest.TestCase):
    def test_preserves_source_timestamps_not_arrival_reconstruction(self):
        # Adjacent chunks may arrive with very different GUI scheduling delays.
        x = np.arange(4., dtype=float).reshape(-1, 1)
        t1, a, b = clean_lsl_chunk(
            [100., 100.01, 100.02, 100.03], x, x + 10
        )
        t2, c, d = clean_lsl_chunk(
            [100.04, 100.05, 100.06, 100.07], x + 4, x + 14, t1[-1]
        )
        np.testing.assert_allclose(np.diff(np.r_[t1, t2]), .01, atol=1e-12)
        np.testing.assert_array_equal(np.r_[a[:, 0], c[:, 0]], np.arange(8.))
        np.testing.assert_array_equal(np.r_[b[:, 0], d[:, 0]], np.arange(10., 18.))

    def test_duplicate_and_backward_samples_are_dropped_together(self):
        t, x, filtered = clean_lsl_chunk(
            [2., 2.01, 1.99, 2.01, 2.02, np.nan, 2.03],
            np.arange(7., dtype=float)[:, None],
            (np.arange(7., dtype=float) + 100)[:, None],
            previous_time=2.,
        )
        np.testing.assert_allclose(t, [2.01, 2.02, 2.03])
        np.testing.assert_allclose(x[:, 0], [1., 4., 6.])
        np.testing.assert_allclose(filtered[:, 0], [101., 104., 106.])
        self.assertTrue(np.all(np.diff(t) > 0))

    def test_old_or_empty_chunk_cannot_reverse_time(self):
        raw = np.array([[1.], [2.]])
        t, _, _ = clean_lsl_chunk([1., 1.5], raw, raw, previous_time=2.)
        self.assertEqual(len(t), 0)

    def test_viewport_selection_uses_real_sample_times(self):
        t = np.array([1., 1.003, 1.011, 1.022, 1.039])
        raw = np.arange(5.)[:, None]
        filtered = raw * 2.
        x, y, z = visible_chunk(t, raw, filtered, 1.01, 1.03)
        np.testing.assert_array_equal(x, [1.011, 1.022])
        np.testing.assert_array_equal(y[:, 0], [2., 3.])
        np.testing.assert_array_equal(z[:, 0], [4., 6.])

    def test_presentation_clock_is_continuous_and_monotonic(self):
        clock = SmoothViewportClock()
        self.assertIsNone(clock.advance(0.))
        clock.observe(100., 10.)
        values = [clock.advance(10. + i/30.) for i in range(30)]
        self.assertTrue(np.all(np.diff(values) >= 0.))
        self.assertLess(values[-1] - values[0], .2)
        # A delayed chunk should not teleport the viewport forward.
        before = clock.advance(11.)
        clock.observe(101., 11.01)
        after = clock.advance(11.04)
        self.assertGreaterEqual(after, before)
        self.assertLessEqual(after - before, .06)
        clock.reset()
        self.assertIsNone(clock.advance(12.))

    def test_clock_stays_bounded_during_lsl_stall(self):
        clock = SmoothViewportClock()
        clock.observe(50., 1.)
        heads = [clock.advance(1. + i/30.) for i in range(250)]
        self.assertTrue(np.all(np.diff(heads) >= 0.))
        self.assertLessEqual(heads[-1], 50.08 + 1e-10)

    def test_misaligned_sample_count_is_rejected(self):
        with self.assertRaises(ValueError):
            clean_lsl_chunk([1., 2.], np.zeros((3, 1)), np.zeros((3, 1)))


if __name__ == '__main__':
    unittest.main()
