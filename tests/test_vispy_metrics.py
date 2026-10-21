"""Metric GPU geometry regression tests; no OpenGL context required."""
import unittest

import numpy as np

from physiolab.metric_display import prepare_metric_curve
from physiolab.vispy_metrics import (
    metric_segments, metric_points, metric_y_limits,
    metric_sweep_segments, metric_sweep_points,
)


class MetricGpuGeometryTests(unittest.TestCase):
    def test_gap_separation_matches_metric_preprocessing(self):
        t = np.array([0., .5, 1., 4., 4.5])
        v = np.array([.1, .2, .3, .8, .9])
        x, y, px, py = prepare_metric_curve(
            t, v, smoothing='none', interpolation='linear', max_gap=1.1
        )
        vertices = metric_segments(x, y)
        self.assertGreater(len(vertices), 0)
        self.assertEqual(len(vertices) % 2, 0)
        # No segment bridges the missing interval [1,4].
        left = vertices[0::2, 0]
        right = vertices[1::2, 0]
        self.assertTrue(np.all(np.abs(right-left) < 1.1))
        points = metric_points(px, py)
        self.assertEqual(len(points), 5)

    def test_no_line_across_nan_or_infinity(self):
        xy = metric_segments(
            np.array([0., 1., 2., 3., 4.]),
            np.array([2., 3., np.nan, 4., 5.]),
        )
        np.testing.assert_allclose(xy, [[0., 2.], [1., 3.], [3., 4.], [4., 5.]])
        xy = metric_segments(np.array([0., 1.]), np.array([np.inf, 2.]))
        self.assertEqual(xy.shape, (0, 2))

    def test_markers_drop_nonfinite_points(self):
        points = metric_points(
            [0, 1, 2, 3], [0, np.nan, 2, np.inf]
        )
        np.testing.assert_allclose(points, [[0., 0.], [2., 2.]])

    def test_limits_follow_only_visible_enabled_curves(self):
        curves = {
            ('EEG', 'AWI'): (
                np.array([[1., 3.], [2., 4.], [60., 1000.]]),
                np.array([[1., 3.], [2., 4.]]),
            ),
        }
        low, high = metric_y_limits(curves, 0., 5.)
        self.assertLess(low, 3.)
        self.assertGreater(high, 4.)
        self.assertLess(high, 20.)
        self.assertEqual(metric_y_limits({}, 0., 5.), (-1., 1.))

    def test_metric_sweep_preserves_old_cycle_and_no_cross_seam(self):
        t = np.arange(0., 6.01, .5)
        y = np.sin(t)
        verts = metric_sweep_segments(t, y, 5., 6.)
        self.assertTrue(len(verts) > 0)
        starts = verts[::2, 0]
        ends = verts[1::2, 0]
        self.assertTrue(np.all(ends >= starts))
        self.assertTrue(np.any(starts < .2))
        self.assertTrue(np.any(starts > .2))
        pts = metric_sweep_points(t, y, 5., 6.)
        self.assertTrue(np.all((pts[:, 0] >= 0.) & (pts[:, 0] <= 1.)))
        self.assertEqual(len(pts), 12)
        t_gap = np.array([4.8, 4.9, 5., 5.1])
        v_gap = np.array([1., 2., 3., 4.])
        segment = metric_sweep_segments(t_gap, v_gap, 5., 5.2)
        self.assertEqual(len(segment), 4)  # two disjoint pairs
        nan_segment = metric_sweep_segments([0., 1., 2., 3.],
                                            [1., 2., np.nan, 4.], 5., 3.)
        self.assertEqual(len(nan_segment), 2)

    def test_rejects_mismatched_arrays(self):
        with self.assertRaises(ValueError):
            metric_segments([0., 1.], [1.])
        with self.assertRaises(ValueError):
            metric_points([0., 1.], [1.])


if __name__ == '__main__':
    unittest.main()
