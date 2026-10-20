"""Metric display processing tests (no Qt or LSL required)."""
import unittest
import numpy as np
from physiolab.metric_display import prepare_metric_curve, monotonic_display_samples


class MetricDisplayTests(unittest.TestCase):
    def test_default_pchip_preserves_samples_at_half_second_cadence(self):
        x = np.arange(0., 5., .5)
        y = np.array([1., 2., 1., 3., 2., 4., 3., 2., 1., 2.])
        dense_x, dense_y, measured_x, measured_y = prepare_metric_curve(x, y)
        self.assertEqual(len(x), 10)
        self.assertGreater(len(dense_x), len(x))
        np.testing.assert_array_equal(measured_x, x)
        np.testing.assert_array_equal(measured_y, y)
        np.testing.assert_allclose(
            np.interp(x, dense_x, dense_y), y, atol=0.003
        )
        # PCHIP never overshoots adjacent values.
        for i in range(len(x)-1):
            interval = dense_y[(dense_x >= x[i]) & (dense_x <= x[i+1])]
            self.assertGreaterEqual(interval.min(), min(y[i], y[i+1])-1e-12)
            self.assertLessEqual(interval.max(), max(y[i], y[i+1])+1e-12)

    def test_missing_measurement_is_not_interpolated_across(self):
        x = np.arange(0., 3., .5)
        y = np.array([1., 2., np.nan, 5., 6., 7.])
        dense_x, dense_y, measured_x, measured_y = prepare_metric_curve(x, y)
        self.assertTrue(np.isnan(dense_x).any())
        self.assertEqual(len(measured_x), 5)
        self.assertTrue(np.all((dense_x[np.isfinite(dense_x)] <= .5) |
                               (dense_x[np.isfinite(dense_x)] >= 1.5)))

    def test_long_gap_is_not_filled(self):
        x = np.array([0., .5, 1., 5., 5.5])
        y = np.array([1., 2., 3., 4., 5.])
        x_out, y_out, _, _ = prepare_metric_curve(x, y)
        self.assertTrue(np.isnan(x_out).any())
        self.assertFalse(np.any((x_out > 1.) & (x_out < 5.)))

    def test_causal_moving_average(self):
        x = np.arange(0., 2.5, .5)
        y = np.array([1., 3., 5., 7., 9.])
        _, avg, actual_x, actual_y = prepare_metric_curve(
            x, y, smoothing='mean', seconds=1., interpolation='none'
        )
        np.testing.assert_allclose(avg, [1., 2., 3., 5., 7.])
        np.testing.assert_array_equal(actual_y, y)

    def test_ema_uses_no_future_observations(self):
        t = np.arange(0., 5., .5)
        v = np.array([1., 3., 2., 1., 8., 9., 2., 4., 5., 1.])
        for method in ('mean', 'ema', 'median'):
            _, first, _, _ = prepare_metric_curve(
                t[:5], v[:5], smoothing=method, seconds=2.,
                interpolation='none'
            )
            _, all_values, _, _ = prepare_metric_curve(
                t, v, smoothing=method, seconds=2.,
                interpolation='none'
            )
            np.testing.assert_allclose(first, all_values[:5])

    def test_nonmonotonic_duplicate_and_invalid_times_do_not_break_pchip(self):
        stamps = [0., .5, .5, .25, 1., np.nan, 1.5, 1.5, 2.]
        vals = [1., 2., 3., 100., 4., 999., 5., 6., 7.]
        x, y = monotonic_display_samples(stamps, vals)
        np.testing.assert_array_equal(x, [0., .5, 1., 1.5, 2.])
        np.testing.assert_array_equal(y, [1., 3., 4., 6., 7.])
        dense_x, dense_y, measured_x, measured_y = prepare_metric_curve(
            stamps, vals, interpolation='pchip'
        )
        self.assertTrue(np.all(np.diff(dense_x) > 0))
        np.testing.assert_array_equal(measured_x, x)
        np.testing.assert_array_equal(measured_y, y)
        self.assertTrue(np.isfinite(dense_y).all())

    def test_nonfinite_times_are_ignored_without_rewriting_metric_values(self):
        x, y, markers_x, markers_y = prepare_metric_curve(
            [np.nan, 1., 1., 2., np.inf, 3.],
            [2., 3., 4., 5., 6., 7.], interpolation='linear'
        )
        np.testing.assert_array_equal(markers_x, [1., 2., 3.])
        np.testing.assert_array_equal(markers_y, [4., 5., 7.])
        self.assertTrue(np.isfinite(x).all())
        self.assertTrue(np.isfinite(y).all())

    def test_invalid_modes_and_nonmonotonic_timestamps(self):
        x, y, measured_x, measured_y = prepare_metric_curve(
            [0., 0.], [1., 2.]
        )
        np.testing.assert_array_equal(measured_x, [0.])
        np.testing.assert_array_equal(measured_y, [2.])
        with self.assertRaises(ValueError):
            prepare_metric_curve([0., .5], [1., 2.], interpolation='wrong')
        with self.assertRaises(ValueError):
            prepare_metric_curve([0., .5], [1., 2.], smoothing='wrong')


if __name__ == '__main__':
    unittest.main()
