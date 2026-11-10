import unittest
import numpy as np
from physiolab.motion_reduction import MotionCanceller, acc_axes
from physiolab.processing import Processor
from physiolab.reference_policy import compatible_references


class MotionReductionTests(unittest.TestCase):
    def test_acc_rejects_legacy_normalization_references(self):
        baseline = dict(metrics={'EEG': {'AWI': {'mean': 1, 'std': 1}},
                                'PPG': {'HR': {'mean': 60, 'std': 5}}})
        refs = compatible_references(baseline, {'EEG': {'motion_reference': {'enabled': True}}}, 10)
        self.assertNotIn('EEG', refs)
        self.assertIn('PPG', refs)

    def test_different_rates_use_only_past_reference_and_recover(self):
        c = MotionCanceller(100, 1, 25)
        t = np.arange(1000)/100
        ref_times = t[::4]
        values = np.column_stack((np.sin(ref_times), np.cos(ref_times), np.sin(ref_times*3)))
        c.append(values, ref_times)
        out = c.process(np.sin(t)[:, None], t)
        self.assertTrue(np.isfinite(out).all())
        self.assertEqual(c.status, 'ACC NLMS active')
        np.testing.assert_array_equal(c.process([[3.]], [11.]), [[3.]])
        c.append([[1., 2., 3.]], [12.])
        np.testing.assert_array_equal(c.process([[3.]], [12.]), [[3.]])
        self.assertEqual(c.trained, 0)  # Restart begins with no measured motion.

    def test_axes_from_mixed_stream(self):
        self.assertEqual(acc_axes(['EEG', 'Acc Z', 'Acc X', 'Acc Y']), (2, 3, 1))
        self.assertIsNone(acc_axes(['GyroX', 'GyroY', 'GyroZ']))
        self.assertIsNone(acc_axes(['X', 'X', 'Y', 'Z']))

    def test_reduces_correlated_noise_and_is_chunk_invariant(self):
        fs = 100
        stamps = np.arange(6000)/fs
        rng = np.random.default_rng(18)
        ref = rng.normal(size=(len(stamps), 3))
        clean = np.sin(2*np.pi*1.3*stamps)
        noise = 2*ref[:, 0] + .7*np.roll(ref[:, 1], 2)
        primary = np.column_stack((clean+noise, 3*clean+.5*noise))
        whole = MotionCanceller(fs, 2, fs)
        # Append in chunks to respect the bounded 40 s reference buffer.
        output = []
        for start in range(0, len(stamps), 500):
            end = start+500
            whole.append(ref[start:end], stamps[start:end])
            output.append(whole.process(primary[start:end], stamps[start:end]))
        output = np.concatenate(output)
        small = MotionCanceller(fs, 2, fs)
        pieces = []
        for start in range(0, len(stamps), 37):
            end = start+37
            small.append(ref[start:end], stamps[start:end])
            pieces.append(small.process(primary[start:end], stamps[start:end]))
        np.testing.assert_allclose(output, np.concatenate(pieces), atol=1e-12)
        expected = np.column_stack((clean, 3*clean))
        self.assertLess(np.mean((output[1000:]-expected[1000:])**2),
                        .2*np.mean((primary[1000:]-expected[1000:])**2))

    def test_missing_stale_future_and_invalid_acc_bypass(self):
        c = MotionCanceller(100, 1, 20)
        x = np.ones((10, 1))
        np.testing.assert_array_equal(c.process(x, np.arange(10)/100), x)
        c.append([[1, 2, 3], [np.nan, 2, 3]], [1., 1.05])
        for stamps in (np.arange(10)/100, 2+np.arange(10)/100, 1.05+np.arange(10)/100):
            np.testing.assert_array_equal(c.process(x, stamps), x)
        self.assertEqual(c.trained, 0)

    def test_primary_gap_resets_and_preserves_baseline(self):
        c = MotionCanceller(100, 1, 100)
        stamps = np.arange(500)/100
        c.append(np.tile([0, 0, 9.81], (500, 1)), stamps)
        np.testing.assert_array_equal(c.process(np.full((500, 1), 8.), stamps), 8.)
        c.append([[1, 2, 3]], [10.])
        np.testing.assert_array_equal(c.process([[8.]], [10.]), [[8.]])
        self.assertEqual(c.trained, 0)

    def test_processor_cleans_input_before_reducer_and_retains_paired_raw(self):
        calls = []
        def transform(x, timestamps):
            calls.append(timestamps.copy())
            return x*.5
        proc = Processor('PPG', 32, 1, ['PPG'],
                         preprocessing=dict(preset='off', notch=False, artifact_reduction='hampel'),
                         timestamp_transform=transform)
        raw = np.sin(np.arange(512)/8)[:, None]
        stamps = np.arange(512)/32
        proc.push(raw, stamps)
        self.assertTrue(calls)
        np.testing.assert_array_equal(calls[0], stamps)
        np.testing.assert_allclose(proc.last_raw_chunk, raw[:len(proc.last_raw_chunk)])
        np.testing.assert_allclose(proc.last_motion_chunk, proc.last_raw_chunk*.5)
        np.testing.assert_allclose(proc.last_filtered_chunk, proc.last_preprocessed_chunk)


if __name__ == '__main__':
    unittest.main()
