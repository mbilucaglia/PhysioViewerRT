"""Per-signal preprocessing presets preserve the previous default path."""
import unittest
import numpy as np
from physiolab.processing import Processor, validate_preprocessing


class FilterPresetTests(unittest.TestCase):
    def test_defaults_preserve_existing_filter_chain(self):
        for kind, fs in [('EEG', 256.), ('PPG', 128.), ('EDA', 32.)]:
            baseline = Processor(kind, fs, 2, ['F3', 'F4'])
            configured = Processor(kind, fs, 2, ['F3', 'F4'],
                                   preprocessing={'preset': 'default',
                                                  'notch': True})
            self.assertEqual(baseline.notch_frequencies,
                             configured.notch_frequencies)
            np.testing.assert_array_equal(baseline.sos, configured.sos)

    def test_presets_produce_finite_processed_samples(self):
        samples = np.random.default_rng(123).normal(size=(512, 2))
        for kind, fs, presets in (
            ('EEG', 256., ('wide', 'focused', 'off')),
            ('PPG', 128., ('pulse', 'wide', 'off')),
            ('EDA', 32., ('smooth_1hz', 'smooth_2hz')),
        ):
            for preset in presets:
                processor = Processor(kind, fs, 2, ['F3', 'F4'],
                                      preprocessing={'preset': preset,
                                                     'notch': False})
                processor.push(samples)
                self.assertTrue(np.isfinite(processor.last_filtered_chunk).all())
                self.assertEqual(processor.notch_frequencies, [])

    def test_invalid_configuration_rejected(self):
        with self.assertRaises(ValueError):
            validate_preprocessing('EEG', preset='not_a_filter')
        with self.assertRaises(ValueError):
            validate_preprocessing('UNKNOWN')

    def test_nonfinite_input_does_not_poison_filter_state(self):
        proc = Processor('EEG', 256., 1, ['O1'])
        for invalid in (np.nan, np.inf, -np.inf):
            with self.assertRaisesRegex(ValueError, 'NaN or infinite'):
                proc.push([[invalid]])
        proc.push(np.ones((256, 1)))
        self.assertTrue(np.isfinite(proc.filtered).all())

    def test_invalid_sampling_rates_rejected(self):
        for fs in (0, -1, np.nan, np.inf):
            with self.assertRaisesRegex(ValueError, 'Sampling rate'):
                Processor('EEG', fs, 1, ['O1'])


if __name__ == '__main__':
    unittest.main()
