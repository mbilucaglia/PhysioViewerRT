import unittest

from physiolab.affect_state import AffectState


def references():
    return {
        'EEG': {'AWI': {'mu': 1., 'sigma': 2.}, 'BAR': {'mu': 4., 'sigma': 2.}},
        'PPG': {'HR': {'mu': 60., 'sigma': 10.}},
        'EDA': {'SCL': {'mu': 2., 'sigma': .5}},
    }


class AffectStateTests(unittest.TestCase):
    def state(self, **kwargs):
        state = AffectState(**kwargs)
        state.set_references(references())
        return state

    def response(self, state, key='central', now=10., retention=60., mode='zscore'):
        return next(response for response in state.snapshot(now, retention, mode).responses
                    if response.key == key)

    def test_shared_normalization_keeps_outliers_and_owns_references(self):
        state = AffectState()
        refs = references()
        state.set_references(refs)
        refs['EEG']['AWI']['sigma'] = 1000.
        state.update('EEG', {'AWI': 21., 'BAR': 2.}, 10.)
        response = self.response(state)
        self.assertEqual((response.current.x, response.current.y), (10., -1.))
        self.assertEqual(response.current.source_times, (10., 10.))
        self.assertFalse(response.current.connected)

    def test_delayed_tonic_pairs_to_past_hr_never_future_hr(self):
        state = self.state()
        state.update('PPG', {'HR': 70.}, 7.5)
        state.update('PPG', {'HR': 90.}, 9.)
        state.update('EDA', {'SCL': 3., '_tonic_at': 8.}, 10.)
        response = self.response(state, 'peripheral')
        self.assertEqual((response.current.x, response.current.y), (1., 2.))
        self.assertEqual(response.current.source_times, (7.5, 8.))
        self.assertEqual(response.current.at, 8.)

    def test_future_only_or_over_skew_hr_has_no_placeholder_dot(self):
        for hr_at in (5., 9.):
            state = self.state(pair_tolerance=1.)
            state.update('PPG', {'HR': 70.}, hr_at)
            state.update('EDA', {'SCL': 3.}, 8.)
            response = self.response(state, 'peripheral')
            self.assertIsNone(response.current)
            self.assertFalse(response.points)

    def test_decomposition_may_arrive_before_causally_eligible_hr(self):
        state = self.state()
        state.update('EDA', {'SCL': 3.}, 8.)
        state.update('PPG', {'HR': 70.}, 8.)
        self.assertIsNotNone(self.response(state, 'peripheral').current)

    def test_normal_eda_diagnostics_do_not_mask_delayed_tonic(self):
        state = self.state()
        state.update('PPG', {'HR': 70.}, 8.)
        state.update('EDA', {'_tonic_status': 'Waiting'}, 11.)
        self.assertFalse(self.response(state, 'peripheral').points)
        state.update('EDA', {'SCL': 3., '_tonic_at': 8.}, 12.)
        self.assertIsNotNone(self.response(state, 'peripheral').current)

    def test_invalid_values_interrupt_only_affected_trail(self):
        state = self.state()
        state.update('EEG', {'AWI': 1., 'BAR': 4.}, 8.)
        state.update('EEG', {'AWI': float('nan'), 'BAR': 4.}, 8.5)
        self.assertIsNone(self.response(state).current)
        state.update('PPG', {'HR': 70.}, 9.)
        state.update('EDA', {'SCL': 3.}, 9.)
        state.update('EEG', {'AWI': 2., 'BAR': 5.}, 9.)
        self.assertFalse(self.response(state).current.connected)
        self.assertIsNotNone(self.response(state, 'peripheral').current)

    def test_duplicate_backward_and_nonfinite_times_do_not_add_points(self):
        state = self.state()
        for at in (9., 9., 8., float('nan'), float('inf')):
            state.update('EEG', {'AWI': 1., 'BAR': 4.}, at)
        self.assertEqual(len(self.response(state).points), 1)

    def test_redraw_does_not_add_observations_and_stale_dot_disappears(self):
        state = self.state()
        state.update('EEG', {'AWI': 1., 'BAR': 4.}, 8.)
        first = self.response(state)
        self.assertEqual(first, self.response(state))
        stale = self.response(state, now=10.01)
        self.assertIsNone(stale.current)
        self.assertEqual(len(stale.points), 1)
        self.assertIn('Stale', stale.status)

    def test_peripheral_latency_allowance_independent_of_central(self):
        state = self.state()
        state.update('EEG', {'AWI': 1., 'BAR': 4.}, 7.)
        state.update('PPG', {'HR': 70.}, 7.)
        state.update('EDA', {'SCL': 3.}, 7.)
        self.assertIsNone(self.response(state).current)
        self.assertIsNotNone(self.response(state, 'peripheral').current)

    def test_capacity_retention_and_gap_connections(self):
        state = self.state(max_points=3)
        for at in (1., 2., 3., 4., 8., 9.):
            state.update('EEG', {'AWI': at, 'BAR': 4.}, at)
        response = self.response(state)
        self.assertEqual([point.at for point in response.points], [4., 8., 9.])
        self.assertEqual([point.connected for point in response.points], [False, False, True])
        self.assertEqual([point.at for point in self.response(state, retention=1.5).points], [9.])
        self.assertFalse(self.response(state, retention=1.5).points[0].connected)

    def test_references_and_provenance_required_identity_not_overlaid(self):
        state = self.state()
        state.update('EEG', {'AWI': 1., 'BAR': 4.}, 10.)
        state.update('PPG', {'HR': 70.}, 10.)
        state.update('EDA', {'SCL': 3.}, 10.)
        self.assertFalse(self.response(state, mode='identity').points)
        state.set_references(references(), tonic_compatible=False)
        self.assertIsNotNone(self.response(state).current)
        self.assertFalse(self.response(state, 'peripheral').points)
        refs = references()
        refs['EEG']['AWI']['sigma'] = 0.
        state.set_references(refs)
        self.assertFalse(self.response(state).points)

    def test_source_reset_and_clear_do_not_connect_old_sessions(self):
        state = self.state()
        state.update('EEG', {'AWI': 1., 'BAR': 4.}, 10.)
        state.update('PPG', {'HR': 70.}, 9.)
        state.update('EDA', {'SCL': 3.}, 9.)
        state.reset('EDA')
        self.assertIsNotNone(self.response(state).current)
        self.assertFalse(self.response(state, 'peripheral').points)
        state.update('EDA', {'SCL': 3.}, 10.)
        self.assertFalse(self.response(state, 'peripheral').points)
        state.clear()
        self.assertTrue(all(not item.points for item in state.snapshot(10., 60.).responses))

    def test_robust_and_minmax_modes_use_existing_unclipped_transform(self):
        state = self.state()
        refs = references()
        for key in ('AWI', 'BAR'):
            refs['EEG'][key].update(median=0., mad=1., iqr=1.349, minimum=0., maximum=2.)
        state.set_references(refs)
        state.update('EEG', {'AWI': 4., 'BAR': 4.}, 10.)
        self.assertAlmostEqual(self.response(state, mode='zmad').current.x, 4. / 1.4826)
        self.assertEqual(self.response(state, mode='robust_iqr').current.x, 4.)
        self.assertEqual(self.response(state, mode='minmax').current.x, 2.)


if __name__ == '__main__':
    unittest.main()
