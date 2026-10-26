"""Exercise the installed streaming ASR library with multichannel EEG."""
import json
import unittest
from unittest.mock import patch

import numpy as np

from physiolab.eeg_asr import ASRError, ASRModel, ASRSettings, StreamingASR, fit_asr
from physiolab.metric_observation import source_configuration
from physiolab.processing import Processor


class EEGASRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fs = 128.
        cls.names = ['F3', 'F4', 'O1', 'O2']
        rng = np.random.default_rng(2026)
        t = np.arange(int(60*cls.fs))/cls.fs
        signal = np.column_stack([10*np.sin(2*np.pi*(9+index*.5)*t+index)
                                  for index in range(4)])
        signal += rng.normal(0, 2, signal.shape)
        cls.raw = signal
        filtering = Processor('EEG', cls.fs, 4, cls.names)
        filtering.push(signal)
        cls.filtered = filtering.last_filtered_chunk
        cls.config = source_configuration('EEG', cls.fs, cls.names, {}, {}, ['uV']*4)
        cls.model = fit_asr(cls.filtered, cls.fs, cls.names, cls.config)

    def test_model_serialization_is_safe_identified_and_immutable(self):
        restored = ASRModel.from_dict(json.loads(json.dumps(self.model.to_dict())))
        self.assertEqual(restored.model_id, self.model.model_id)
        self.assertFalse(restored.M.flags.writeable)
        invalid = restored.to_dict()
        invalid['M'][0][0] += 1.
        with self.assertRaises(ASRError):
            ASRModel.from_dict(invalid)

    def test_clean_stream_preserves_samples_and_original_input(self):
        processor = StreamingASR(self.model)
        data = self.filtered[:int(4*self.fs)].copy()
        original = data.copy()
        output = []
        for start in range(0, len(data), 13):
            output.append(processor.process(data[start:start+13]))
        output = np.concatenate(output)
        self.assertEqual(output.shape, data.shape)
        self.assertTrue(np.isfinite(output).all())
        np.testing.assert_array_equal(data, original)
        self.assertLess(np.sqrt(np.mean((output-data)**2)), np.std(data)*.25)
        self.assertLessEqual(sum(processor._processor._counter), int(2*self.fs))

    def test_large_transient_is_attenuated_without_a_noise_reference(self):
        processor = StreamingASR(self.model)
        data = self.filtered[:int(6*self.fs)].copy()
        start, stop = int(2*self.fs), int(4*self.fs)
        artifact = 1000*np.sin(2*np.pi*4*np.arange(stop-start)/self.fs)
        data[start:stop, 0] += artifact
        blocks, corrections = [], []
        for i in range(0, len(data), 32):
            blocks.append(processor.process(data[i:i+32]))
            corrections.append(processor.last_chunk_corrected)
        output = np.concatenate(blocks)
        self.assertTrue(any(corrections), 'Injected artifacts must trigger reconstruction telemetry')
        region = slice(int(3*self.fs), stop)
        self.assertLess(np.std(output[region,0]), np.std(data[region,0])*.7)
        self.assertEqual(output.shape, data.shape)

    def test_reset_replays_deterministically_and_backend_errors_are_named(self):
        processor = StreamingASR(self.model)
        data = self.filtered[:64]
        first = processor.process(data)
        processor.reset()
        np.testing.assert_allclose(processor.process(data), first)
        with patch.object(processor._processor, 'transform', side_effect=RuntimeError('test failure')):
            with self.assertRaisesRegex(ASRError, 'test failure'):
                processor.process(data)

    def test_correction_telemetry_tracks_backend_reconstruction_and_release(self):
        processor = StreamingASR(self.model)
        data = np.zeros((4, 4))
        def transform(block):
            processor._processor.state_['R'] = matrix[0]
            return block
        matrix = [np.eye(4)]
        with patch.object(processor._processor, 'transform', side_effect=transform):
            processor.process(data)
            self.assertFalse(processor.last_chunk_corrected)
            matrix[0] = np.diag([0., 1., 1., 1.])
            processor.process(data)
            self.assertTrue(processor.last_chunk_corrected)
            matrix[0] = np.eye(4)
            processor.process(data)
            self.assertTrue(processor.last_chunk_corrected, 'release blend still reconstructs')
            processor.process(data)
            self.assertFalse(processor.last_chunk_corrected)
        processor.reset()
        self.assertFalse(processor.last_chunk_corrected)

    def test_selected_training_uses_continuously_prefiltered_windows(self):
        from physiolab.asr_tasks import fit_training_asr
        eeg = {'data': self.raw, 'fs': self.fs, 'channels': self.names,
               'timestamps': np.arange(len(self.raw))/self.fs,
               'preprocessed_data': self.filtered,
               'accepted_window_samples': [128]*60, 'units': ['uV']*4}
        # Selection gaps between windows are allowed; gaps inside windows are not.
        eeg['timestamps'][30*128:] += 5.
        model = fit_training_asr(eeg)
        self.assertEqual(model.channels, tuple(self.names))
        self.assertEqual(model.baseline_seconds, 60.)
        eeg['timestamps'][10] += .3
        with self.assertRaises(ValueError):
            fit_training_asr(eeg)

    def test_cutoff_update_matches_refit_without_relearning_or_changing_calibration(self):
        for cutoff in (5., 25.):
            expected = fit_asr(self.filtered, self.fs, self.names, self.config, ASRSettings(cutoff=cutoff))
            with patch('physiolab.eeg_asr._backend', side_effect=AssertionError('No fitting permitted')):
                updated = self.model.with_cutoff(cutoff)
            np.testing.assert_allclose(updated.T, expected.T, rtol=1e-10, atol=1e-12)
            for name in ('M', 'A', 'B', 'threshold_center', 'threshold_spread', 'threshold_basis'):
                np.testing.assert_array_equal(getattr(updated,name), getattr(self.model,name))
            self.assertEqual(updated.clean_seconds, self.model.clean_seconds)
            self.assertEqual(updated.baseline_seconds, self.model.baseline_seconds)
            self.assertNotEqual(updated.model_id, self.model.model_id)
            restored = ASRModel.from_dict(updated.to_dict())
            np.testing.assert_array_equal(restored.with_cutoff(20.).T, self.model.T)
        legacy = self.model.to_dict()
        for name in ('threshold_center', 'threshold_spread', 'threshold_basis', 'model_id'):
            legacy.pop(name)
        with self.assertRaisesRegex(ASRError, 'lacks cached threshold'):
            ASRModel.from_dict(legacy).with_cutoff(25.)

    def test_invalid_baseline_and_configuration_are_rejected(self):
        for data, fs, names in ((self.filtered[:100], self.fs, self.names),
                                (np.ones_like(self.filtered), self.fs, self.names),
                                (self.filtered, 64., self.names),
                                (self.filtered[:,:1], self.fs, self.names[:1])):
            with self.subTest(fs=fs,channels=len(names)), self.assertRaises(ASRError):
                fit_asr(data, fs, names, self.config)
        for settings in ({'cutoff':1.}, {'step_seconds':2.}, {'maxdims':.9}):
            with self.assertRaises(ASRError):
                ASRSettings(**settings)

    def test_processor_applies_transform_after_filter_before_metrics(self):
        plain = Processor('EEG', self.fs, 4, self.names)
        transformed = Processor('EEG', self.fs, 4, self.names, sample_transform=lambda x:x*.5)
        plain.push(self.raw[:256])
        transformed.push(self.raw[:256])
        np.testing.assert_allclose(transformed.last_preprocessed_chunk, plain.last_filtered_chunk)
        np.testing.assert_allclose(transformed.last_filtered_chunk, plain.last_filtered_chunk*.5)
        np.testing.assert_array_equal(transformed.raw, plain.raw)

    def test_baselines_and_live_metrics_share_channel_preserving_correction(self):
        from physiolab.calibration import analyze_bsl, analyze_eyc
        from physiolab.asr_tasks import eeg_reference_analysis
        eeg = {'data': self.raw, 'fs': self.fs, 'channels': self.names,
               'timestamps': np.arange(len(self.raw))/self.fs, 'units': ['uV']*4}
        cleaned = analyze_bsl({'EEG': eeg}, 10., self.model)
        replay = eeg_reference_analysis(eeg, {}, 10., self.model)
        self.assertEqual(cleaned['metrics']['EEG'], replay['metrics']['EEG'])
        self.assertEqual(cleaned['source_configurations']['EEG']['channels'], self.names)
        self.assertEqual(cleaned['source_configurations']['EEG']['asr_model_id'], self.model.model_id)
        eye = analyze_eyc(eeg, self.model)
        self.assertEqual(eye['eeg_asr_model_id'], self.model.model_id)
        self.assertEqual(eye['posterior_channels'], ['O1', 'O2'])
        self.assertTrue(7. <= eye['iaf_hz'] <= 13.)
        self.assertEqual(eeg['data'].shape, self.raw.shape)

    def test_baseline_lifecycle_preserves_independent_training_model(self):
        from physiolab.asr_session import ASRSession
        session = ASRSession()
        session.set_training({'data': self.raw, 'fs': self.fs, 'channels': self.names})
        session.install_fit(self.model)
        session.set_enabled(True)
        generation = session.generation
        for analysis in ({'metrics': {'EEG': {}}}, None):
            session.set_baseline(analysis)
            self.assertIs(session.model, self.model)
            self.assertTrue(session.enabled)
            self.assertEqual(session.generation, generation)

    def test_backend_cannot_remove_channels(self):
        processor = StreamingASR(self.model)
        block = self.filtered[:64]
        with patch.object(processor._processor, 'transform', return_value=block.T[:3]):
            with self.assertRaisesRegex(ASRError, 'invalid data'):
                processor.process(block)
        self.assertEqual(self.model.channels, tuple(self.names))
