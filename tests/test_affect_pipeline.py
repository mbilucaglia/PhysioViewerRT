"""Actual baseline/decomposition and observation-provenance contracts."""
import unittest
import numpy as np

from physiolab.calibration import analyze_bsl, normalize
from physiolab.metric_catalog import DEFAULT_METRICS
from physiolab.metric_observation import MetricObservation
from physiolab.metric_state import MetricState
from physiolab.processing import Processor
from physiolab.sc_decomposition import TonicSCProcessor, sc_pipeline_metadata
from physiolab.source_conversion import SourceConversion


class AffectPipelineTests(unittest.TestCase):
    def test_baseline_references_match_the_live_filtered_tonic_pipeline(self):
        fs = 32.
        timestamps = 100.+np.arange(int(60*fs))/fs
        data = (4.+.02*np.sin(np.arange(len(timestamps)) / fs * .5))[:, None]
        preprocessing = {'preset': 'smooth_1hz', 'notch': True}
        conversion = SourceConversion().metadata()
        baseline = analyze_bsl({'EDA': {'data': data, 'timestamps': timestamps,
            'fs': fs, 'channels': ['SC'], 'units': ['uS'],
            'preprocessing': preprocessing, 'conversion': conversion}})
        if not TonicSCProcessor().available:
            self.skipTest('cvxEDA dependency unavailable')
        filtering = Processor('EDA', fs, 1, ['SC'], preprocessing=preprocessing)
        tonic = TonicSCProcessor(unit='µS')
        values = []
        for start in range(0, len(data), 16):
            filtering.push(data[start:start+16])
            values.extend(tonic.push(filtering.last_filtered_chunk,
                                     timestamps[start:start+16], fs))
        reference = baseline['metrics']['EDA']['SCL']
        self.assertAlmostEqual(reference['mu'], np.mean([item.value for item in values]))
        self.assertEqual(reference['valid_windows'], 60)
        for mode in ('zscore', 'zmad', 'robust_iqr', 'minmax'):
            self.assertTrue(np.isfinite(normalize(values[-1].value, reference, mode)), mode)
        self.assertEqual(baseline['tonic_sc']['configuration_id'],
                         sc_pipeline_metadata(tonic, filtering.preprocessing, conversion)['configuration_id'])
        self.assertNotEqual(baseline['tonic_sc']['configuration_id'],
                         sc_pipeline_metadata(tonic, {'preset': 'off', 'notch': True}, conversion)['configuration_id'])
        self.assertEqual(set(baseline['metrics']['EDA']), {'SCL'})
        self.assertEqual([item.name for item in DEFAULT_METRICS if item.modality == 'EDA'], ['SCL'])

    def test_async_metric_keeps_its_value_and_does_not_fabricate_measurements(self):
        state = MetricState(DEFAULT_METRICS)
        observation = MetricObservation(4., 5., 6., 8., 'µS', 'cvxeda-test').metadata()
        state.update('EDA', {'SCL': 4., '_tonic_at': 6.,
                            '_observations': {'SCL': observation}}, 8.)
        state.update('EDA', {'_tonic_status': 'Collecting SC'}, 8.5)
        self.assertEqual(state.latest['EDA']['SCL'], 4.)
        self.assertEqual(len(state.history['EDA','SCL']), 1)
        self.assertEqual(state.observations['EDA','SCL'][-1]['window_end'], 6.)
        state.reset('EDA')
        self.assertFalse(state.observations['EDA','SCL'])

    def test_provenance_rejects_reversed_or_invalid_source_windows(self):
        for start, end in ((2., 1.), (float('nan'), 2.)):
            with self.subTest(start=start), self.assertRaises(ValueError):
                MetricObservation(1., start, end, 3., 'µS', 'test')

    def test_tonic_scl_drives_ei_while_diagnostics_do_not_add_measurements(self):
        state = MetricState(DEFAULT_METRICS)
        reference = {'mu': 1., 'sigma': 1.}
        state.ei.set_references(reference, reference)
        state.update('PPG', {'HR': 2.}, 10.)
        state.update('EDA', {'SCL': 2., '_partial': True}, 10.)
        self.assertIsNotNone(state.latest['EI']['EI'])
        ei_before = list(state.history['EI', 'EI'])
        scl_before = list(state.history['EDA', 'SCL'])
        state.update('EDA', {'_tonic_status': 'Collecting SC', '_partial': True,
                             '_sc_samples': np.ones((1000, 2))}, 10.1)
        self.assertEqual(state.latest['EDA']['SCL'], 2.)
        self.assertNotIn('_sc_samples', state.latest['EDA'])
        self.assertEqual(list(state.history['EDA', 'SCL']), scl_before)
        self.assertEqual(list(state.history['EI', 'EI']), ei_before)
        state.update('EDA', {'SCL': None}, 10.2)
        self.assertIsNone(state.latest['EI']['EI'])

    def test_ei_uses_latest_inputs_without_time_alignment_or_age_gates(self):
        from physiolab.emotion import emotional_index_from_bsl
        state = MetricState(DEFAULT_METRICS)
        hr_ref, scl_ref = {'mu': 60., 'sigma': 10.}, {'mu': 4., 'sigma': 2.}
        state.ei.set_references(hr_ref, scl_ref)
        state.update('PPG', {'HR': 70., '_observations': {'HR': {'window_end': 8.}}}, 10.)
        state.update('PPG', {'HR': 100., '_observations': {'HR': {'window_end': 10.}}}, 10.1)
        state.update('EDA', {'SCL': 5., '_tonic_at': 8., '_partial': True}, 11.)
        self.assertAlmostEqual(state.latest['EI']['EI'],
                              emotional_index_from_bsl(100., 5., hr_ref, scl_ref))
        state.update('PPG', {'HR': 75., '_observations': {'HR': {'window_end': 12.}}}, 12.1)
        self.assertAlmostEqual(state.latest['EI']['EI'],
                              emotional_index_from_bsl(75., 5., hr_ref, scl_ref))
        state.update('PPG', {'HR':80., '_observations':{'HR':{'window_end':200.}}}, 200.)
        self.assertAlmostEqual(state.latest['EI']['EI'],
                              emotional_index_from_bsl(80., 5., hr_ref, scl_ref))
        state.update('EDA', {'SCL':None}, 201.)
        self.assertIsNone(state.latest['EI']['EI'])

    def test_short_window_eda_calculator_never_provides_predecomposition_scl(self):
        proc = Processor('EDA', 32., 1, ['SC'])
        metric = proc.push(np.full((32, 1), 5.))
        self.assertNotIn('SCL', metric)
        self.assertIn('cvxEDA', metric['status'])
