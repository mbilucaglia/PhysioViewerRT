"""Boundary behavior without QApplication or worker construction."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from physiolab.metric_observation import eeg_configuration, source_configuration
from physiolab.reference_policy import compatible_references
from physiolab.calibration import load_calibration
from physiolab.calibration_coordinator import CalibrationCoordinator
from physiolab.asr_training_policy import TrainingPolicy
from physiolab.receiver_state import freeze, thaw


class ConfigurationTests(unittest.TestCase):
    def test_helper_keeps_defaults_order_and_input(self):
        for extra in ({}, {'units': ['mV', 'uV'], 'conversion': {'gain': 2},
                           'preprocessing': {'preset': 'wide', 'notch': False}}):
            eeg = {'fs': 256, 'channels': ['O2', 'O1'], **extra}
            before = deepcopy(eeg)
            result = eeg_configuration(eeg)
            self.assertEqual(result, source_configuration('EEG', 256, ['O2', 'O1'],
                eeg.get('preprocessing'), eeg.get('conversion'), eeg.get('units') or ['', '']))
            self.assertEqual(eeg, before)


class ReferencePolicyTests(unittest.TestCase):
    def setUp(self):
        self.analysis = {'metrics': {'EEG': {'AWI': {'mu': 1}}, 'PPG': {'HR': {'mu': 2}},
                                    'EDA': {'SCL': {'mu': 3}}, 'EI': {'EI': {'mu': 4}}},
                         'iaf_hz_used': 10., 'tonic_sc': {'configuration_id': 'tonic'},
                         'source_configurations': {'EEG': {'channels': ['O1']}}}

    def test_each_incompatibility_removes_only_dependent_references(self):
        before = deepcopy(self.analysis)
        for options, missing in (
                ({}, set()), ({'replay_pending': True}, {'EEG'}),
                ({'replay_error': 'failed'}, {'EEG'}), ({'asr_enabled': True}, {'EEG'}),
                ({'tonic_configuration': None}, {'EDA', 'EI'})):
            with self.subTest(options=options):
                result = compatible_references(self.analysis, {}, 10.,
                    **({'tonic_configuration': 'tonic'} | options))
                self.assertEqual(set(result), set(self.analysis['metrics']) - missing)
        self.assertEqual(self.analysis, before)
        self.assertNotIn('EEG', compatible_references(self.analysis, {}, 11.))
        self.assertNotIn('EEG', compatible_references(self.analysis,
                         {'EEG': {'channels': ['O2']}}, 10.))
        self.assertIn('EEG', compatible_references(self.analysis, {}, 10.))

    def test_missing_hr_and_empty_baseline(self):
        self.analysis['metrics']['PPG'] = {}
        self.assertNotIn('EI', compatible_references(self.analysis, {}, 10.,
                                                    tonic_configuration='tonic'))
        self.assertEqual(compatible_references({}, {}, 10.), {})


class SessionTransitionTests(unittest.TestCase):
    def test_training_retry_limit_timeout_and_late_result(self):
        policy = TrainingPolicy(60., 300.)
        status = {'accepted_seconds': 60., 'accepted_samples': 60, 'maximum_samples': 180}
        self.assertEqual(policy.action(status, 100.), 'fit')
        policy.start_fit({'samples': 60})
        self.assertEqual(policy.action(status, 101.), 'wait')
        self.assertFalse(policy.complete(None, 'retry', 60.))
        self.assertEqual(policy.next_seconds, 70.)
        self.assertEqual(policy.action(status, 102.), 'wait')
        self.assertEqual(policy.action({**status, 'accepted_seconds': 70.}, 103.), 'fit')
        self.assertEqual(policy.action({**status, 'maximum_samples': 60}, 103.), 'stop')
        self.assertEqual(policy.action(status, 301.), 'stop')
        policy.cancel()
        self.assertFalse(policy.complete(object(), None, 70.))
        self.assertIsNone(policy.model)

    def test_replay_owns_original_and_derived_data_and_ignores_old_generation(self):
        state = CalibrationCoordinator()
        data = np.ones((3, 1))
        streams = {'EEG': {'data': data, 'timestamps': np.arange(3.), 'fs': 128., 'channels': ['O1']}}
        baseline = {'metrics': {'PPG': {'HR': {'mu': 60.}}}, 'iaf_hz_used': 10.}
        state.apply('BSL', {'analysis': baseline}, streams=streams)
        data[:] = 5.
        self.assertTrue(np.all(state.streams['EEG']['data'] == 1.))
        self.assertFalse(state.streams['EEG']['data'].flags.writeable)
        old = state.request_replay(None, None)[0]
        new = state.request_replay(None, None)[0]
        result = {'eyc': None, 'bsl': {'metrics': {'EEG': {}}}, 'iaf_hz': 11.}
        self.assertIsNone(state.complete_replay(old, result, None, True))
        self.assertEqual(state.iaf_hz, 10.)
        self.assertTrue(state.complete_replay(new, result, None, True))
        self.assertEqual(state.base_analysis, baseline)
        self.assertEqual(state.loaded_bsl['analysis'], result['bsl'])
        state.clear('BSL')
        self.assertIsNone(state.loaded_bsl)
        self.assertEqual(state.streams, {})

    def test_invalid_apply_and_failed_replay_preserve_active_values(self):
        state = CalibrationCoordinator()
        state.apply('EYC', {'analysis': {'iaf_hz': 10.}})
        with self.assertRaises(ValueError):
            state.apply('EYC', {'analysis': {'iaf_hz': float('nan')}})
        self.assertEqual(state.loaded_eyc['analysis']['iaf_hz'], 10.)
        state.complete_replay(state.reference_generation, None, 'failed', False)
        self.assertEqual(state.iaf_hz, 10.)
        self.assertEqual(state.error, 'failed')

    def test_nested_snapshot_cannot_be_mutated_and_compatibility_copy_is_detached(self):
        original = {'channels': ['O1'], 'preprocessing': {'notch': False}}
        frozen = freeze(original)
        original['channels'].append('O2')
        with self.assertRaises(TypeError):
            frozen['preprocessing']['notch'] = True
        mutable = thaw(frozen)
        mutable['channels'].append('O3')
        self.assertEqual(thaw(frozen)['channels'], ['O1'])


class CalibrationValidationTests(unittest.TestCase):
    def write(self, path, descriptor=None, data=None, timestamps=None, **meta_updates):
        meta = {'schema': 1, 'type': 'EYC', 'streams': {'EEG':
                {'fs': 128., 'channels': ['O1'], **(descriptor or {})}}, **meta_updates}
        np.savez(path, metadata=np.array(json.dumps(meta)),
                 EEG_data=np.ones((3, 1)) if data is None else data,
                 EEG_timestamps=np.arange(3.) if timestamps is None else timestamps)

    def test_invalid_recordings_rejected_before_analysis(self):
        cases = [({'descriptor': {'fs': value}}, 'frequency') for value in (-1, 0, float('nan'), True)]
        cases += [({'data': np.array([[np.nan], [1.], [2.]])}, 'finite'),
                  ({'data': np.ones((0, 1)), 'timestamps': np.array([])}, 'dimensions'),
                  ({'timestamps': np.array([[0.], [1.], [2.]])}, 'dimensions'),
                  ({'timestamps': np.array([0., 1., 1.])}, 'increasing'),
                  ({'timestamps': np.array([2., 1., 0.])}, 'increasing'),
                  ({'descriptor': {'channels': ['O1', 'O2']}}, 'dimensions'),
                  ({'descriptor': {'samples': 4}}, 'sample count'),
                  ({'descriptor': {'units': ['uV', 'uV']}}, 'units'),
                  ({'streams': {}}, 'streams'), ({'schema': 9}, 'schema')]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.npz'
            for values, message in cases:
                with self.subTest(values=values):
                    self.write(path, **values)
                    with self.assertRaisesRegex(ValueError, message):
                        load_calibration(path, 'EYC')

    def test_legacy_optional_fields_preserved_and_missing_arrays_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.npz'
            self.write(path)
            _, streams = load_calibration(path, 'EYC')
            self.assertEqual(streams['EEG']['units'], [])
            self.assertEqual(streams['EEG']['preprocessing'], {})
            np.testing.assert_array_equal(streams['EEG']['timestamps'], np.arange(3.))
            np.savez(path, metadata=np.array(json.dumps({'schema': 1, 'type': 'EYC',
                'streams': {'EEG': {'fs': 128., 'channels': ['O1']}}})))
            with self.assertRaisesRegex(ValueError, 'Missing signal arrays'):
                load_calibration(path, 'EYC')
