"""VisPy rendering geometry tests, without requiring VisPy or an OpenGL context."""
import unittest
import numpy as np
from physiolab.vispy_raw import trace_segments


class VisPyGeometryTests(unittest.TestCase):
    def test_independent_multichannel_segments(self):
        t = np.array([0., .5, 1.])
        traces = np.column_stack((np.array([1., 2., 3.]),
                                  np.array([7., 8., 9.])))
        pos, colors = trace_segments(t, traces, 0., 1., lower=0., upper=10.)
        self.assertEqual(pos.shape, (8, 2))  # 2 channels * 2 gaps * 2 endpoints
        self.assertEqual(colors.shape, (8, 4))
        np.testing.assert_allclose(pos[:4, 0], [0, .5, .5, 1.])
        np.testing.assert_allclose(pos[4:, 1], [.7, .8, .8, .9])
        self.assertTrue(np.isfinite(pos).all())
        self.assertFalse(np.array_equal(colors[0], colors[4]))

    def test_missing_data_cuts_lines_not_channels(self):
        t = np.arange(4.)
        x = np.array([[1., 7.], [2., 8.], [np.nan, 9.], [4., 10.]])
        pos, colors = trace_segments(t, x, 0, 3, lower=0, upper=12)
        # ch0: one valid segment; ch1: three valid segments
        self.assertEqual(len(pos), 8)
        self.assertEqual(len(colors), 8)

    def test_invisible_time_intervals_and_invalid_inputs(self):
        pos, _ = trace_segments(np.array([-3., -2., -1.]),
                                np.ones((3, 1)), 0, 3)
        self.assertEqual(len(pos), 0)
        for args in [
            (np.array([1., 2.]), np.zeros((3, 1)), 0., 1.),
            (np.array([1., 2.]), np.zeros((2, 1)), 2., 2.),
        ]:
            with self.assertRaises(ValueError):
                trace_segments(*args)

    def test_empty_buffer(self):
        pos, colors = trace_segments(np.array([]), np.empty((0, 8)), 0., 1.)
        self.assertEqual(pos.shape, (0, 2))
        self.assertEqual(colors.shape, (0, 4))


if __name__ == '__main__':
    unittest.main()
