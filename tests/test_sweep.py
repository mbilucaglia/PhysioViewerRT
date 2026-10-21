"""Stable previous-cycle sweep geometry, independent of OpenGL."""
import unittest
import numpy as np
from physiolab.vispy_raw import sweep_segments


class SweepTests(unittest.TestCase):
    def test_previous_cycle_remains_on_right_and_new_cycle_draws_left(self):
        duration = 5.
        head = 6.
        times = np.arange(0., 6.01, .5)
        values = np.arange(len(times), dtype=float)[:, None]
        pos, colors = sweep_segments(times, values, duration, head)
        self.assertEqual(pos.shape[1], 2)
        self.assertEqual(len(colors), len(pos))
        starts, ends = pos[0::2, 0], pos[1::2, 0]
        self.assertTrue(np.all(ends >= starts))  # no wrap-joining diagonal
        self.assertTrue(np.all((starts >= 0.) & (starts <= 1.)))
        self.assertTrue(np.all(ends <= 1.))
        # At head=6 (phase 1 second), previous cycle is still visible
        # from 1s through 5s, and current cycle fills 0 to 1s.
        self.assertTrue(np.any(starts < .2))
        self.assertTrue(np.any(starts > .2))

    def test_full_cycle_does_not_connect_across_boundary(self):
        times = np.array([4.8, 4.9, 5., 5.1])
        values = np.zeros((4, 1))
        pos, _ = sweep_segments(times, values, 5., 5.2)
        start, end = pos[0::2, 0], pos[1::2, 0]
        self.assertTrue(np.all(end >= start))
        self.assertEqual(len(start), 2)

    def test_uniform_gain_does_not_shift_channel_baselines(self):
        times = np.array([1., 1.1, 1.2])
        # Signals already carry channel offsets at 0 and 6.
        values = np.array([[1., 7.], [2., 8.], [3., 9.]])
        original, _ = sweep_segments(times, values, 5., 1.2, scale=1.)
        doubled, _ = sweep_segments(times, values, 5., 1.2, scale=2.)
        self.assertEqual(original.shape, doubled.shape)
        self.assertTrue(np.all(doubled[:, 1] > original[:, 1]))
        # Both channels' deviations grow by the same factor, with their
        # independent 0 and 6 display-unit baselines unchanged.
        np.testing.assert_allclose(
            doubled[:, 1] - original[:, 1],
            np.array([1., 2., 2., 3., 1., 2., 2., 3.]) / 15.
        )

    def test_rejects_invalid_duration_gain_shape(self):
        with self.assertRaises(ValueError):
            sweep_segments([0, 1], np.zeros((2, 1)), 0., 1.)
        with self.assertRaises(ValueError):
            sweep_segments([0, 1], np.zeros((2, 1)), 5., 1., scale=0.)
        with self.assertRaises(ValueError):
            sweep_segments([0, 1], np.zeros((3, 1)), 5., 1.)


if __name__ == '__main__':
    unittest.main()
