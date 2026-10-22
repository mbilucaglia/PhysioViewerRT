"""Regression coverage for the stateful physiological LSL simulator."""
import unittest
import numpy as np

from physiolab.synthetic import SyntheticPhysiology, SPECS, EEG_LABELS


class SyntheticPhysiologyTests(unittest.TestCase):
    def test_eeg_montage_and_source_metadata(self):
        fs, names = SPECS['EEG']
        self.assertEqual(fs, 256)
        self.assertEqual(len(names), 32)
        self.assertEqual(len(set(names)), 32)
        for electrode in ('F3', 'F4', 'O1', 'O2', 'Pz', 'Fp1', 'Fp2'):
            self.assertIn(electrode, EEG_LABELS)

    def test_finite_nonconstant_and_expected_shapes(self):
        generator = SyntheticPhysiology(seed=42)
        for kind, (fs, names) in SPECS.items():
            x = generator.generate(kind, 0, 5*fs)
            self.assertEqual(x.shape, (5*fs, len(names)))
            self.assertEqual(x.dtype, np.float32)
            self.assertTrue(np.isfinite(x).all())
            self.assertGreater(np.std(x), 1.e-4)

    def test_same_seed_is_reproducible(self):
        for kind, (fs, _) in SPECS.items():
            a = SyntheticPhysiology(seed=8)
            b = SyntheticPhysiology(seed=8)
            result_a = a.generate(kind, 0, fs*3)
            result_b = b.generate(kind, 0, fs*3)
            np.testing.assert_array_equal(result_a, result_b)

    def test_chunk_splitting_does_not_change_stream(self):
        # Important for LSL: generator output cannot depend on pull timing.
        for kind, (fs, _) in SPECS.items():
            full = SyntheticPhysiology(seed=20).generate(kind, 0, 6*fs)
            split = SyntheticPhysiology(seed=20)
            segments = []
            tick = 0
            # Keep total below 6*fs even for EDA at 32 Hz.
            for samples in (13, fs, 7, 2*fs, 2*fs):
                segments.append(split.generate(kind, tick, samples))
                tick += samples
            self.assertGreater(6*fs - tick, 0)
            segments.append(split.generate(kind, tick, 6*fs-tick))
            np.testing.assert_allclose(full, np.vstack(segments),
                                       atol=2e-5, rtol=1e-6)

    def test_eda_chunk_invariance_through_phasic_responses_and_tail_cutoff(self):
        fs = SPECS['EDA'][0]
        count = 230 * fs
        full = SyntheticPhysiology(seed=20).generate('EDA', 0, count)
        split = SyntheticPhysiology(seed=20)
        chunks = [split.generate('EDA', start, min(fs, count - start))
                  for start in range(0, count, fs)]
        # Includes multiple responses, their decay tails and the fixed age cutoff.
        np.testing.assert_array_equal(full, np.vstack(chunks))

    def test_artifacts_are_present_and_configurable(self):
        for kind, (fs, _) in SPECS.items():
            a = SyntheticPhysiology(seed=99, artifact_level='none')
            b = SyntheticPhysiology(seed=99, artifact_level='strong')
            x = a.generate(kind, 0, fs*95)
            y = b.generate(kind, 0, fs*95)
            self.assertGreater(float(np.max(np.abs(x-y))), .1)
            self.assertTrue(np.isfinite(y).all())

    def test_invalid_artifact_level_and_sample_order(self):
        with self.assertRaises(ValueError):
            SyntheticPhysiology(artifact_level='unknown')
        model = SyntheticPhysiology()
        model.generate('EEG', 0, 100)
        with self.assertRaises(ValueError):
            model.generate('EEG', 0, 10)

    def test_hr_and_scl_change_over_time(self):
        gen = SyntheticPhysiology(seed=123, artifact_level='none')
        scl = gen.generate('EDA', 0, 100*SPECS['EDA'][0])[:, 0]
        ppg = gen.generate('PPG', 0, 100*SPECS['PPG'][0])[:, 0]
        self.assertGreater(np.std(np.array([
            np.median(scl[i:i+320]) for i in range(0, len(scl), 320)
        ])), .04)
        self.assertGreater(np.std(ppg[:PPG_RATE*10]), .05)


PPG_RATE = SPECS['PPG'][0]


if __name__ == '__main__':
    unittest.main()
