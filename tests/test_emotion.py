"""Regression checks for stage-1 within-signal HR/GSR z-scores and EI."""
import unittest
import numpy as np

from physiolab.emotion import (
    RollingEmotionalIndex, emotional_index_z, baseline_ei, standardize_pair,
)
from physiolab.calibration import normalize, summarize_metric


class EmotionalIndexRegressionTests(unittest.TestCase):
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

    def test_rolling_requires_sixty_seconds(self):
        model = RollingEmotionalIndex(seconds=60)
        for i in range(105):  # 52.5 seconds
            t = i * .5
            model.update('PPG', 70 + 4*np.sin(i*.12), t)
            model.update('EDA', 3 + .2*np.cos(i*.12), t)
        self.assertIsNone(model.value(52.))
        for i in range(105, 121):
            t = i*.5
            model.update('PPG', 70 + 4*np.sin(i*.12), t)
            model.update('EDA', 3 + .2*np.cos(i*.12), t)
        value = model.value(60.)
        self.assertIsNotNone(value)
        self.assertGreaterEqual(value, -1)
        self.assertLessEqual(value, 1)

    def test_missing_hr_suppresses_ei(self):
        model = RollingEmotionalIndex()
        for i in range(125):
            t = i*.5
            model.update('PPG', 68+4*np.sin(i*.1), t)
            model.update('EDA', 3+.2*np.cos(i*.1), t)
        self.assertIsNotNone(model.value(62.))
        for i in range(125, 130):
            model.update('EDA', 3+.2*np.cos(i*.1), i*.5)
        self.assertIsNone(model.value(64.5))

    def test_invalid_baseline_gives_no_ei(self):
        hr = np.full(120, 70.0)
        gsr = np.linspace(3, 4, 120)
        self.assertTrue(np.isnan(baseline_ei(hr, gsr)).all())


if __name__ == '__main__':
    unittest.main()
