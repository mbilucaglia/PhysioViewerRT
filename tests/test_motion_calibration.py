"""NLMS is upstream of processing, IAF, baselines and portable replay."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

from physiolab.processing import Processor
from physiolab.calibration import analyze_eyc, analyze_bsl
from physiolab.calibration_session import CalibrationSession
from physiolab.calibration_storage import save_calibration, load_calibration
from physiolab.calibration_coordinator import recording_snapshot
from physiolab.motion_recording import recorded_input
from physiolab.reference_policy import compatible_references


MOTION = dict(algorithm='acc-nlms-v2-input', source_id='test-acc',
              channels=[0, 1, 2], fs=50., enabled=True)


class MotionCalibrationTests(unittest.TestCase):
    @staticmethod
    def eeg():
        fs = 128.
        t = np.arange(int(60*fs))/fs
        clean = np.column_stack((np.sin(2*np.pi*10*t), .8*np.sin(2*np.pi*10*t+.3)))
        raw = clean + 8*np.sin(2*np.pi*8*t)[:, None]
        return dict(data=raw, motion_cleaned=clean, motion_reference=deepcopy(MOTION),
                    timestamps=t, fs=fs, channels=['O1', 'O2'], units=['uV']*2,
                    preprocessing=dict(preset='default', notch=False))

    def test_input_cleaning_precedes_filters_and_asr(self):
        raw = np.linspace(-5, 5, 200)[:, None]
        clean = np.clip(raw, -1, 1)
        stamps = np.arange(200)/100
        asr_inputs = []
        def asr(data):
            asr_inputs.append(data.copy())
            return data+2
        actual = Processor('EEG', 100, 1, ['O1'],
                           timestamp_transform=lambda x, ts: np.clip(x, -1, 1), sample_transform=asr)
        expected = Processor('EEG', 100, 1, ['O1'])
        actual.push(raw, stamps)
        expected.push(clean, stamps)
        np.testing.assert_array_equal(actual.last_raw_chunk, raw)
        np.testing.assert_array_equal(actual.last_motion_chunk, clean)
        np.testing.assert_array_equal(asr_inputs[0], expected.last_filtered_chunk)
        np.testing.assert_array_equal(actual.last_filtered_chunk, expected.last_filtered_chunk+2)

    def test_buffered_peripheral_capture_keeps_raw_and_cleaned_pairs_across_gap(self):
        proc = Processor('PPG', 32, 1, ['PPG'],
                         preprocessing=dict(preset='off', notch=False, artifact_reduction='wavelet'),
                         timestamp_transform=lambda x, ts: x*.25)
        for origin in (0., 20.):
            output = []
            for i in range(20):
                stamps = origin+np.arange(i*16, (i+1)*16)/32
                raw = np.sin(stamps)[:, None]
                proc.push(raw, stamps)
                if len(proc.last_filtered_chunk):
                    np.testing.assert_allclose(proc.last_raw_chunk[:, 0], np.sin(proc.last_timestamps))
                    np.testing.assert_allclose(proc.last_motion_chunk, proc.last_raw_chunk*.25)
                    output.extend(proc.last_timestamps)
            self.assertTrue(output)
            self.assertGreaterEqual(min(output), origin)

    def test_capture_boundary_and_schema2_roundtrip_preserve_both_stages(self):
        eeg = self.eeg()
        metadata = {k: v for k, v in eeg.items() if k not in ('data', 'timestamps', 'motion_cleaned')}
        metadata['start_lsl_timestamp'] = .25
        capture = CalibrationSession('EYC', {'EEG': metadata}, deadline=100.)
        for start in range(0, len(eeg['data']), 64):
            sl = slice(start, start+64)
            capture.append('EEG', eeg['data'][sl], eeg['timestamps'][sl], eeg['channels'], eeg['fs'], 1.,
                           motion_cleaned=eeg['motion_cleaned'][sl])
        recording = capture.finish()
        mask = eeg['timestamps'] > .25
        np.testing.assert_array_equal(recording['EEG']['data'], eeg['data'][mask])
        np.testing.assert_array_equal(recording['EEG']['motion_cleaned'], eeg['motion_cleaned'][mask])
        before = analyze_eyc(recording['EEG'])
        self.assertAlmostEqual(before['iaf_hz'], 10., delta=.03)
        raw_iaf = analyze_eyc({k: v for k, v in eeg.items() if not k.startswith('motion_')})['iaf_hz']
        self.assertLess(raw_iaf, 8.1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'eyc.npz'
            save_calibration(path, 'EYC', recording, before)
            meta, loaded = load_calibration(path, 'EYC')
            self.assertEqual(meta['schema'], 2)
            self.assertEqual(analyze_eyc(loaded['EEG']), before)
            np.testing.assert_array_equal(loaded['EEG']['data'], recording['EEG']['data'])
        snapshot = recording_snapshot(recording)
        self.assertFalse(snapshot['EEG']['motion_cleaned'].flags.writeable)

    def test_baselines_use_cleaned_eeg_ppg_sc_and_allow_matching_normalization(self):
        streams = {'EEG': self.eeg()}
        for kind, fs in [('PPG', 64.), ('EDA', 32.)]:
            t = np.arange(int(fs*60))/fs
            clean = (np.sin(2*np.pi*1.2*t) if kind == 'PPG' else np.full(len(t), 5.))[:, None]
            raw = (np.sin(2*np.pi*1.8*t) if kind == 'PPG' else np.full(len(t), 12.))[:, None]
            streams[kind] = dict(data=raw, motion_cleaned=clean, motion_reference=deepcopy(MOTION),
                fs=fs, timestamps=t, channels=[kind], units=['a.u.' if kind == 'PPG' else 'µS'])
        baseline = analyze_bsl(streams, 10.)
        manual = {kind: {**{k: v for k, v in item.items() if not k.startswith('motion_')},
                         'data': item['motion_cleaned']} for kind, item in streams.items()}
        expected = analyze_bsl(manual, 10.)
        self.assertEqual(baseline['metrics'], expected['metrics'])
        self.assertAlmostEqual(baseline['metrics']['PPG']['HR']['mu'], 72., delta=1.)
        self.assertAlmostEqual(baseline['metrics']['EDA']['SCL']['mu'], 5., delta=.01)
        refs = compatible_references(baseline, baseline['source_configurations'], 10.,
                                    tonic_configuration=baseline['tonic_sc']['configuration_id'])
        for kind in ('EEG', 'PPG', 'EDA'):
            self.assertIn(kind, refs)
        mismatch = deepcopy(baseline['source_configurations'])
        mismatch['PPG']['motion_reference']['source_id'] = 'different-sensor'
        self.assertNotIn('PPG', compatible_references(baseline, mismatch, 10.))

    def test_missing_or_corrupt_adaptive_output_never_falls_back_to_raw(self):
        eeg = self.eeg()
        for broken in (None, np.zeros((1, 2)), np.full_like(eeg['data'], np.nan)):
            with self.assertRaisesRegex(ValueError, 'post-NLMS'):
                recorded_input({**eeg, 'motion_cleaned': broken})
        capture = CalibrationSession('EYC', {'EEG': eeg}, deadline=100.)
        capture.append('EEG', eeg['data'], eeg['timestamps'], eeg['channels'], eeg['fs'], 1.)
        with self.assertRaisesRegex(ValueError, 'post-NLMS'):
            capture.finish()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bad.npz'
            meta = dict(schema=2, type='EYC', streams={'EEG': {
                'fs': eeg['fs'], 'channels': eeg['channels'], 'motion_reference': MOTION}})
            np.savez(path, metadata=np.array(json.dumps(meta)), EEG_data=eeg['data'],
                     EEG_timestamps=eeg['timestamps'])
            with self.assertRaisesRegex(ValueError, 'post-NLMS'):
                load_calibration(path, 'EYC')


if __name__ == '__main__':
    unittest.main()
