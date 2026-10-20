"""Regression checks for stage-1 within-signal HR/GSR z-scores and EI."""
import unittest
import math
import numpy as np

from physiolab.emotion import (
    BaselineEmotionalIndex, emotional_index_from_bsl, emotional_index_z,
    baseline_ei, standardize_pair, ei_matrix, ei_epochs,
)
from physiolab.calibration import normalize, summarize_metric


class EmotionalIndexRegressionTests(unittest.TestCase):
    def test_matlab_ei_matrix_quadrants(self):
        """Direct MATLAB EI_matrix reference: atan2(GSR, HR), then beta."""
        samples = [
            (1., 1.), (1., -1.), (-1., -1.), (-1., 1.),
            (1., 0.), (-1., 0.),
        ]
        for hr_z, gsr_z in samples:
            with self.subTest(hr_z=hr_z, gsr_z=gsr_z):
                theta = math.atan2(gsr_z, hr_z)
                beta = math.pi / 2 - theta
                if gsr_z >= 0 and hr_z <= 0:
                    beta = 2.5 * math.pi - theta
                matlab_ei = 1 - beta / math.pi
                self.assertAlmostEqual(
                    emotional_index_z(hr_z, gsr_z), matlab_ei, places=12
                )
        self.assertIsNone(emotional_index_z(0., 0.))

    def test_matlab_ei_axis_order_and_quadrant_sign(self):
        self.assertAlmostEqual(emotional_index_z(1., 1.), .75)
        self.assertAlmostEqual(emotional_index_z(1., -1.), .25)
        self.assertAlmostEqual(emotional_index_z(-1., -1.), -.25)
        self.assertAlmostEqual(emotional_index_z(-1., 1.), -.75)
        self.assertIsNone(emotional_index_z(0., 1.))
        self.assertIsNone(emotional_index_z(0., -1.))

    def test_matlab_ei_matrix_epoch_vector_and_zero_guard(self):
        hr = np.array([1., 1., -1., -1., 0., 0., np.nan])
        scl = np.array([1., -1., -1., 1., 1., -1., 1.])
        observed = ei_matrix(scl, hr)
        np.testing.assert_allclose(
            observed[:6], [.75, .25, -.25, -.75, -1., 0.],
            atol=1e-12,
        )
        self.assertTrue(np.isnan(observed[6]))
        self.assertTrue(np.isnan(ei_matrix([1., -1.], [0., 0.])).all())
        with self.assertRaises(ValueError):
            ei_matrix([1., 2.], [1.])

    def test_matlab_normalize_then_ei_per_epoch(self):
        hr_ref = {'mu': 70., 'sigma': 5.}
        scl_ref = {'mu': 4., 'sigma': .5}
        hr_epochs = [
            np.array([75., 75., 65., 65.]),
            np.array([75., 70., 65.]),
        ]
        scl_epochs = [
            np.array([4.5, 3.5, 3.5, 4.5]),
            np.array([4.5, 4.5, 4.]),
        ]
        result = ei_epochs(scl_epochs, hr_epochs, scl_ref, hr_ref)
        self.assertEqual(len(result), 2)
        np.testing.assert_allclose(result[0], [.75, .25, -.25, -.75], atol=1e-12)
        np.testing.assert_allclose(result[1], [.75, -1., -.5], atol=1e-12)
        self.assertAlmostEqual(result[1][0], emotional_index_from_bsl(
            75., 4.5, hr_ref, scl_ref,
        ))
        with self.assertRaises(ValueError):
            ei_epochs(scl_epochs[:1], hr_epochs, scl_ref, hr_ref)

    def test_signal_standardization_not_reference(self):
        t = np.linspace(0, 3*np.pi, 120)
        hr = 70 + 9*np.sin(t)
        scl = 4 + 0.4*np.cos(t)
        h, g = standardize_pair(hr, scl)
        self.assertAlmostEqual(float(np.mean(h)), 0, places=10)
        self.assertAlmostEqual(float(np.std(g, ddof=1)), 1, places=10)
        expected = emotional_index_z(h[-1], g[-1])
        self.assertAlmostEqual(float(baseline_ei(hr, scl)[-1]), expected, places=10)
        # Additive/multiplicative shifts cannot change within-signal z-scores.
        np.testing.assert_allclose(
            baseline_ei(hr, scl), baseline_ei(3*hr+100, 4*scl+20), atol=1e-12
        )

    def test_ei_reference_applies_to_ei_not_hr(self):
        t = np.linspace(0, 4*np.pi, 120)
        ei_series = baseline_ei(70+7*np.sin(t), 5+.3*np.cos(t))
        ref = summarize_metric(ei_series)
        self.assertIsNotNone(ref)
        raw_ei = float(ei_series[-1])
        self.assertAlmostEqual(
            normalize(raw_ei, ref, 'zscore'),
            (raw_ei-ref['mu'])/ref['sigma']
        )
        self.assertAlmostEqual(normalize(raw_ei, ref, 'identity'), raw_ei)

    def test_live_ei_uses_bsl_means_and_sigmas_immediately(self):
        hr_ref = {'mu': 70., 'sigma': 5.}
        scl_ref = {'mu': 3., 'sigma': .5}
        expected = emotional_index_z(1., -1.)
        self.assertAlmostEqual(
            emotional_index_from_bsl(75., 2.5, hr_ref, scl_ref), expected
        )
        model = BaselineEmotionalIndex(hr_ref, scl_ref)
        model.update('PPG', 75., 1.)
        model.update('EDA', 2.5, 1.1)
        self.assertAlmostEqual(model.value(1.1), expected)
        self.assertIsNone(model.value(2.2))

    def test_missing_or_zero_variance_bsl_rejects_ei(self):
        valid_hr = {'mu': 70., 'sigma': 5.}
        valid_scl = {'mu': 3., 'sigma': .5}
        self.assertIsNone(emotional_index_from_bsl(
            75., 2.5, valid_hr, {'mu': 3., 'sigma': 0.}
        ))
        self.assertIsNone(emotional_index_from_bsl(
            75., 2.5, None, valid_scl
        ))
        self.assertIsNone(emotional_index_from_bsl(
            None, 2.5, valid_hr, valid_scl
        ))
        model = BaselineEmotionalIndex()
        model.update('PPG', 75., 1.)
        model.update('EDA', 2.5, 1.)
        self.assertIsNone(model.value(1.))
        model.set_references(valid_hr, valid_scl)
        self.assertIsNotNone(model.value(1.))
        model.update('PPG', None, 1.2)
        self.assertIsNone(model.value(1.2))

    def test_ei_baseline_reference_is_independent_of_display_normalization(self):
        hr = np.linspace(65., 76., 120)
        scl = 3.5 + .2 * np.sin(np.linspace(0., 6*np.pi, 120))
        raw = baseline_ei(hr, scl)
        ref = summarize_metric(raw)
        hr_stats = summarize_metric(hr)
        scl_stats = summarize_metric(scl)
        value = emotional_index_from_bsl(
            73., 3.65, hr_stats, scl_stats
        )
        self.assertIsNotNone(value)
        self.assertAlmostEqual(normalize(value, ref, 'identity'), value)
        self.assertAlmostEqual(
            normalize(value, ref, 'zscore'), (value-ref['mu']) / ref['sigma']
        )

    def test_invalid_baseline_gives_no_ei(self):
        hr = np.full(120, 70.0)
        gsr = np.linspace(3, 4, 120)
        self.assertTrue(np.isnan(baseline_ei(hr, gsr)).all())


if __name__ == '__main__':
    unittest.main()
