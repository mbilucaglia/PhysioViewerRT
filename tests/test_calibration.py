"""Synthetic calibration tests. Run: python -m unittest discover -s tests -v"""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from physiolab.calibration import (
    analyze_eyc, analyze_bsl, normalize, save_calibration, load_calibration,
)


class CalibrationTests(unittest.TestCase):
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
            'fs': fs, 'channels': ['EDA'], 'data': eda[:, None]
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

    def test_roundtrip(self):
        fs = 128
        t = np.arange(fs * 60) / fs
        record = {'EEG': {'fs': fs, 'channels': ['O1', 'O2'],
                          'data': np.column_stack((np.sin(2*np.pi*10*t),
                                                   np.sin(2*np.pi*10*t))),
                          'timestamps': t + 100}}
        analysis = analyze_eyc(record['EEG'])
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'eyc.npz'
            save_calibration(file, 'EYC', record, analysis)
            meta, loaded = load_calibration(file, 'EYC')
            self.assertEqual(meta['type'], 'EYC')
            np.testing.assert_allclose(loaded['EEG']['data'], record['EEG']['data'])
            self.assertAlmostEqual(meta['analysis']['iaf_hz'], 10, delta=.1)
            with self.assertRaisesRegex(ValueError, 'type'):
                load_calibration(file, 'BSL')


if __name__ == '__main__':
    unittest.main()
