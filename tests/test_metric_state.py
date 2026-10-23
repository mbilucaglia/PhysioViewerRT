import unittest
import numpy as np

from physiolab.metric_catalog import DEFAULT_METRICS, MetricDefinition
from physiolab.metric_state import MetricState


class MetricStateTests(unittest.TestCase):
    def test_dynamic_metric_history_is_bounded_and_missing_values_are_gaps(self):
        state = MetricState([MetricDefinition('EEG', 'Added')], history_capacity=2)
        state.update('EEG', {'Added': 3}, 0)
        state.update('EEG', {}, 1)
        state.update('EEG', {'Added': 7}, 2)
        points = list(state.history['EEG', 'Added'])
        self.assertEqual([point[0] for point in points], [1., 2.])
        self.assertTrue(np.isnan(points[0][1]))
        self.assertEqual(points[1][1], 7.)

    def test_derived_ei_and_reset_preserve_other_modalities_and_references(self):
        state = MetricState(DEFAULT_METRICS)
        ref = {'mu': 1., 'sigma': 1.}
        state.ei.set_references(ref, ref)
        state.update('EEG', {'AWI': 2.}, 0.)
        state.update('PPG', {'HR': 2.}, 1.)
        state.update('EDA', {'SCL': 2.}, 1.)
        self.assertIsNotNone(state.latest['EI']['EI'])
        state.reset('EDA')
        self.assertNotIn('EI', state.latest)
        self.assertFalse(state.ei.latest)
        self.assertFalse(state.history['EI', 'EI'])
        self.assertEqual(state.latest['EEG']['AWI'], 2.)
        self.assertIs(state.ei.hr_reference, ref)

    def test_normalization_uses_metric_specific_references_and_iaf_identity(self):
        refs = {'EEG': {'AWI': {'mu': 2., 'sigma': 2.}}}
        self.assertEqual(MetricState.normalized_value('EEG', 'AWI', 6., 'zscore', refs), 2.)
        self.assertEqual(MetricState.normalized_value('EEG', 'IAF', 10., 'zscore', {}), 10.)
        self.assertIsNone(MetricState.normalized_value('EDA', 'SCL', 2., 'zscore', refs))
        self.assertIsNone(MetricState.normalized_value('EEG', 'AWI', np.nan, 'identity', refs))

    def test_none_update_does_not_change_observations(self):
        state = MetricState(DEFAULT_METRICS)
        state.update('EEG', None, 0.)
        self.assertFalse(state.latest)
        self.assertTrue(all(not history for history in state.history.values()))

    def test_ei_unavailable_status_identifies_the_actual_missing_requirement(self):
        state = MetricState(DEFAULT_METRICS)
        ref = {'mu':1., 'sigma':1.}
        state.update('PPG', {'HR':2.}, 1.)
        self.assertIn('BSL HR reference', state.latest['EI']['status'])
        state.ei.set_references({'mu':1., 'sigma':0.}, ref)
        state.update('EDA', {'SCL':2.}, 1.)
        self.assertIn('no usable variability', state.latest['EI']['status'])
        state.ei.set_references(ref, ref)
        state.update('PPG', {'HR':1.}, 2.)
        state.update('EDA', {'SCL':2.}, 2.)
        self.assertIsNotNone(state.latest['EI']['EI'])
        state.update('PPG', {'HR':2.}, 2.5)
        state.update('EDA', {'SCL':2.}, 2.5)
        self.assertIsNotNone(state.latest['EI']['EI'])
        self.assertIn('z-scores', state.latest['EI']['status'])

    def test_ei_original_signed_value_needs_no_extra_display_reference(self):
        for mode in ('identity','zscore','zmad','robust_iqr','minmax'):
            self.assertEqual(MetricState.normalized_value('EI','EI',-.4,mode,{}), -.4)
