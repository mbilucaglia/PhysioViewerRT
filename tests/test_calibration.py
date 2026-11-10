"""Synthetic calibration tests. Run: python -m unittest discover -s tests -v"""
import tempfile
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from physiolab.calibration import (
    analyze_eyc, analyze_bsl, normalize, save_calibration, load_calibration,
    samples_after_timestamp,
)


class CalibrationTests(unittest.TestCase):
    def test_bsl_has_no_predecomposition_scl_or_ei_fallback(self):
        fs = 32.
        t = np.arange(int(fs * 60)) / fs
        with patch('physiolab.sc_decomposition.decompose_baseline', return_value=[]):
            result = analyze_bsl({'EDA': {
                'fs': fs, 'channels': ['SC'], 'data': (4 + np.sin(t))[:, None],
                'timestamps': 100. + t}})
        self.assertNotIn('SCL', result['metrics'].get('EDA', {}))
        self.assertNotIn('EI', result['metrics'])
        self.assertIsNone(result['tonic_sc'])

    def test_bsl_ei_uses_same_tonic_reference_factors_and_source_pairing_as_live(self):
        from physiolab.emotion import emotional_index_z
        from physiolab.processing import Processor
        fs = 32.
        t = np.arange(int(fs * 60)) / fs
        times = t + 100.
        pulse = np.sin(2 * np.pi * (1.2 * t + .04 * np.sin(t * .1)))[:, None]
        sc = (4 + np.sin(t * .1))[:, None]
        tonic = [SimpleNamespace(window_end=100. + second,
                                 value=4. + np.sin(second * .1))
                 for second in range(1, 60)]
        streams = {
            'EDA': {'fs': fs, 'channels': ['SC'], 'data': sc, 'timestamps': times},
            'PPG': {'fs': fs, 'channels': ['Pulse'], 'data': pulse, 'timestamps': times},
        }
        with patch('physiolab.sc_decomposition.decompose_baseline', return_value=tonic):
            result = analyze_bsl(streams)
        hr_ref = result['metrics']['PPG']['HR']
        scl_ref = result['metrics']['EDA']['SCL']
        proc = Processor('PPG', fs, 1, ['Pulse'])
        hr = []
        for start in range(0, len(t), 16):
            metric = proc.push(pulse[start:start + 16])
            if metric:
                hr.append((times[start + 15], metric['HR']))
        expected = []
        latest = {}
        events = [(at,'HR',value) for at,value in hr]
        events.extend((observation.window_end,'SCL',observation.value) for observation in tonic)
        for at, name, measured in sorted(events, key=lambda event:event[0]):
            latest[name] = measured
            if latest.get('HR') is None or latest.get('SCL') is None:
                continue
            value = emotional_index_z(
                normalize(latest['HR'], hr_ref, 'zscore'),
                normalize(latest['SCL'], scl_ref, 'zscore'))
            if value is not None:
                expected.append(value)
        self.assertAlmostEqual(result['metrics']['EI']['EI']['mu'], np.mean(expected))
        self.assertEqual(result['metrics']['EI']['EI']['valid_windows'], len(expected))
        self.assertEqual(set(result['metrics']['EDA']), {'SCL'})

    def test_eyc_posterior_center_of_gravity(self):
        fs = 128
        t = np.arange(fs * 60) / fs
        rng = np.random.default_rng(42)
        # 10-Hz activity on the two posterior channels, distractor at 12 Hz frontal.
        data = np.column_stack([
            15 * np.sin(2*np.pi*12*t) + rng.normal(0, .2, len(t)),
            9 * np.sin(2*np.pi*10*t) + rng.normal(0, .2, len(t)),
            8 * np.sin(2*np.pi*10*t + .3) + rng.normal(0, .2, len(t)),
        ])
        result = analyze_eyc({'fs': fs, 'channels': ['F3', 'O1', 'PO8'], 'data': data})
        self.assertEqual(result['posterior_channels'], ['O1', 'PO8'])
        self.assertAlmostEqual(result['iaf_hz'], 10., delta=.2)
        self.assertIn('Welch', result['method'])

    def test_eyc_requires_posterior(self):
        with self.assertRaisesRegex(ValueError, 'posterior'):
            analyze_eyc({'fs': 128, 'channels': ['F3'],
                         'data': np.ones((128 * 60, 1))})

    def test_bsl_stats_include_iqr_and_median(self):
        fs = 32
        t = np.arange(fs * 60) / fs
        eda = 4 + .1 * np.sin(2*np.pi*.04*t)
        result = analyze_bsl({'EDA': {
            'fs': fs, 'channels': ['EDA'], 'data': eda[:, None], 'timestamps': t + 100
        }})
        stats = result['metrics']['EDA']['SCL']
        self.assertGreater(stats['valid_windows'], 30)
        self.assertGreater(stats['sigma'], 0)
        self.assertGreater(stats['iqr'], 0)
        self.assertAlmostEqual(stats['median'], 4., delta=.15)

    def test_fixed_reference_transforms(self):
        reference = dict(mu=3., sigma=2., median=3., mad=1., iqr=2.,
                         minimum=1., maximum=5.)
        self.assertEqual(normalize(5., None, 'identity'), 5.)
        self.assertEqual(normalize(5., reference, 'zscore'), 1.)
        self.assertAlmostEqual(normalize(5., reference, 'zmad'), 2/1.4826)
        self.assertAlmostEqual(normalize(5., reference, 'minmax'), 1.)
        self.assertIsNone(normalize(5., {**reference, 'sigma': 0.}, 'zscore'))

    def test_queued_samples_before_start_do_not_enter_calibration(self):
        data = np.arange(6., dtype=float)[:, None]
        timestamps = np.array([100., 100.1, 100.2, 100.3, 100.4, 100.5])
        kept, stamps = samples_after_timestamp(data, timestamps, 100.25)
        np.testing.assert_array_equal(stamps, timestamps[3:])
        np.testing.assert_array_equal(kept[:, 0], [3., 4., 5.])
        empty, empty_times = samples_after_timestamp(data, timestamps, 101.)
        self.assertEqual(empty.shape, (0, 1))
        self.assertEqual(len(empty_times), 0)

    def test_calibration_boundary_rejects_invalid_timestamp(self):
        data = np.arange(4., dtype=float)[:, None]
        out, stamps = samples_after_timestamp(
            data, [np.nan, 10., 10.5, np.inf], 10.
        )
        np.testing.assert_array_equal(stamps, [10.5])
        np.testing.assert_array_equal(out[:, 0], [2.])
        with self.assertRaises(ValueError):
            samples_after_timestamp(data, [10.], 9.)

    def test_roundtrip(self):
        fs = 128
        t = np.arange(fs * 60) / fs
        record = {'EEG': {'fs': fs, 'channels': ['O1', 'O2'],
                          'data': np.column_stack((np.sin(2*np.pi*10*t),
                                                   np.sin(2*np.pi*10*t))),
                          'timestamps': t + 100,
                          'preprocessing': {'preset': 'wide', 'notch': False},
                          'conversion': {'gain': .001, 'offset': 2., 'output_unit': 'µV'},
                          'source_units': ['mV', 'mV'], 'units': ['µV', 'µV']}}
        analysis = analyze_eyc(record['EEG'])
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'eyc.npz'
            save_calibration(file, 'EYC', record, analysis)
            meta, loaded = load_calibration(file, 'EYC')
            self.assertEqual(meta['type'], 'EYC')
            self.assertEqual(loaded['EEG']['preprocessing'], record['EEG']['preprocessing'])
            self.assertEqual(loaded['EEG']['conversion'], record['EEG']['conversion'])
            self.assertEqual(loaded['EEG']['source_units'], ['mV', 'mV'])
            self.assertEqual(loaded['EEG']['units'], ['µV', 'µV'])
            np.testing.assert_allclose(loaded['EEG']['data'], record['EEG']['data'])
            self.assertAlmostEqual(meta['analysis']['iaf_hz'], 10, delta=.1)
            with self.assertRaisesRegex(ValueError, 'type'):
                load_calibration(file, 'BSL')


class CalibrationPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.streams = {'EEG': {
            'fs': 128., 'channels': ['O1'],
            'data': np.arange(16., dtype=float)[:, None],
            'timestamps': 100. + np.arange(16) / 128.,
        }}

    def test_failed_compression_preserves_previous_file_or_absent_destination(self):
        for kind in ('EYC', 'BSL'):
            for exists in (False, True):
                for partial in (False, True):
                    with self.subTest(kind=kind, exists=exists, partial=partial), \
                            tempfile.TemporaryDirectory() as folder:
                        path = Path(folder) / 'calibration.npz'
                        if exists:
                            save_calibration(path, kind, self.streams, {'previous': True})
                        before = path.read_bytes() if exists else None

                        def fail_write(handle, **arrays):
                            if partial:
                                handle.write(b'incomplete ZIP archive')
                                handle.flush()
                            raise OSError('injected compression failure')

                        with patch('physiolab.calibration_storage.np.savez_compressed',
                                   side_effect=fail_write):
                            with self.assertRaisesRegex(OSError, 'injected compression'):
                                save_calibration(path, kind, self.streams, {'previous': False})
                        if exists:
                            self.assertEqual(path.read_bytes(), before)
                            meta, _ = load_calibration(path, kind)
                            self.assertEqual(meta['analysis'], {'previous': True})
                        else:
                            self.assertFalse(path.exists())
                        self.assertEqual(set(Path(folder).iterdir()), {path} if exists else set())

    def test_io_failures_preserve_destination_and_remove_temporary(self):
        make_temporary = tempfile.NamedTemporaryFile

        class FailingFile:
            def __init__(self, file, stage):
                self.file, self.stage = file, stage

            def __getattr__(self, name):
                return getattr(self.file, name)

            def __enter__(self):
                return self

            def flush(self):
                if self.stage == 'flush':
                    raise OSError('injected flush failure')
                self.file.flush()

            def __exit__(self, *args):
                self.file.close()
                if self.stage == 'close':
                    raise OSError('injected close failure')

        for stage in ('create', 'flush', 'sync', 'close', 'replace'):
            for exists in (False, True):
                with self.subTest(stage=stage, exists=exists), \
                        tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / 'calibration.npz'
                    if exists:
                        save_calibration(path, 'EYC', self.streams, {'previous': True})
                    before = path.read_bytes() if exists else None
                    error = OSError(f'injected {stage} failure')
                    if stage in ('flush', 'close'):
                        injection = patch('physiolab.calibration_storage.tempfile.NamedTemporaryFile',
                            side_effect=lambda **kw: FailingFile(make_temporary(**kw), stage))
                    else:
                        target = {'create': 'tempfile.NamedTemporaryFile',
                                  'sync': 'os.fsync', 'replace': 'os.replace'}[stage]
                        injection = patch('physiolab.calibration_storage.' + target, side_effect=error)
                    with injection:
                        with self.assertRaisesRegex(OSError, f'injected {stage}'):
                            save_calibration(path, 'EYC', self.streams, {'previous': False})
                    self.assertEqual(path.read_bytes() if path.exists() else None, before)
                    self.assertEqual(set(Path(folder).iterdir()), {path} if exists else set())

    def test_success_commits_complete_schema_one_archive_without_extra_files(self):
        replace_file = os.replace
        for kind in ('EYC', 'BSL'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                # The API keeps the exact supplied filename, even without .npz.
                path = Path(folder) / 'calibration without extension'
                for revision in (1, 2):
                    before = path.read_bytes() if path.exists() else None

                    def commit(source, destination):
                        self.assertEqual(Path(source).parent, path.parent)
                        self.assertEqual(path.read_bytes() if path.exists() else None, before)
                        meta, loaded = load_calibration(source, kind)
                        self.assertEqual(meta['schema'], 1)
                        self.assertEqual(meta['analysis'], {'revision': revision})
                        np.testing.assert_array_equal(loaded['EEG']['data'],
                                                      self.streams['EEG']['data'])
                        replace_file(source, destination)

                    with patch('physiolab.calibration_storage.os.replace', side_effect=commit) as replace:
                        save_calibration(str(path), kind, self.streams, {'revision': revision})
                    replace.assert_called_once()
                    meta, loaded = load_calibration(path, kind)
                    self.assertEqual(meta['analysis'], {'revision': revision})
                    np.testing.assert_array_equal(loaded['EEG']['timestamps'],
                                                  self.streams['EEG']['timestamps'])
                    self.assertEqual(set(Path(folder).iterdir()), {path})

    def test_cleanup_failure_keeps_original_error_and_reports_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'calibration.npz'
            save_calibration(path, 'EYC', self.streams, {})
            before = path.read_bytes()
            error = OSError('injected replace failure')
            with patch('physiolab.calibration_storage.os.replace', side_effect=error), \
                    patch('physiolab.calibration_storage.os.unlink', side_effect=PermissionError('in use')):
                with self.assertRaises(OSError) as caught:
                    save_calibration(path, 'EYC', self.streams, {})
            self.assertIs(caught.exception, error)
            self.assertEqual(path.read_bytes(), before)
            leftovers = set(Path(folder).iterdir()) - {path}
            self.assertEqual(len(leftovers), 1)
            self.assertIn(str(leftovers.pop()), error.__notes__[0])

    def test_validation_failure_does_not_touch_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'calibration.npz'
            save_calibration(path, 'EYC', self.streams, {})
            before = path.read_bytes()
            invalid = {'EEG': {**self.streams['EEG'], 'data': np.array([[np.nan]])}}
            with self.assertRaises(ValueError):
                save_calibration(path, 'EYC', invalid, {})
            with self.assertRaises(TypeError):
                save_calibration(path, 'EYC', self.streams, {'invalid': object()})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(set(Path(folder).iterdir()), {path})

    @unittest.skipUnless(os.name == 'nt', 'Windows open-file replacement semantics')
    def test_windows_destination_in_use_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'calibration.npz'
            save_calibration(path, 'EYC', self.streams, {'previous': True})
            before = path.read_bytes()
            with path.open('rb'):
                with self.assertRaises(PermissionError):
                    save_calibration(path, 'EYC', self.streams, {'previous': False})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(set(Path(folder).iterdir()), {path})

    def test_relative_destination_keeps_exact_filename(self):
        with tempfile.TemporaryDirectory(dir='.') as folder:
            path = Path(os.path.relpath(Path(folder) / 'relative calibration'))
            self.assertFalse(path.is_absolute())
            save_calibration(path, 'BSL', self.streams, {'relative': True})
            meta, _ = load_calibration(path, 'BSL')
            self.assertEqual(meta['analysis'], {'relative': True})
            self.assertEqual(set(path.parent.iterdir()), {path})


if __name__ == '__main__':
    unittest.main()
