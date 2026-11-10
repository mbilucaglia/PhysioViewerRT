"""Reproducible ACC, causal motion coupling, quiet/resume and NLMS efficacy."""
import unittest
import numpy as np
from physiolab.synthetic import SyntheticPhysiology, SPECS
from physiolab.synthetic_motion import ACC_SPECS, GRAVITY, MOTION_ONSETS
from physiolab.motion_reduction import MotionCanceller


class SyntheticMotionTests(unittest.TestCase):
    def test_none_preserves_physiology_and_emits_stationary_acc(self):
        for kind, (fs, _) in SPECS.items():
            original = SyntheticPhysiology(seed=10)
            explicit = SyntheticPhysiology(seed=10, motion_level='none')
            np.testing.assert_array_equal(original.generate(kind, 0, fs*50),
                                          explicit.generate(kind, 0, fs*50))
            acc = explicit.generate_acc(kind, 0, ACC_SPECS[kind][0]*50)
            np.testing.assert_array_equal(acc, np.tile(np.array([0., 0., GRAVITY], np.float32), (len(acc), 1)))
            np.testing.assert_array_equal(explicit.motion_artifact(kind, 0, fs*50), 0.)

    def test_distinct_acc_streams_and_seeded_call_order_independence(self):
        a = SyntheticPhysiology(seed=7, motion_level='strong')
        b = SyntheticPhysiology(seed=7, motion_level='strong')
        for kind in reversed(SPECS):
            b.generate(kind, 0, SPECS[kind][0]*40)
        signals = {}
        for kind, (fs, _) in ACC_SPECS.items():
            signals[kind] = a.generate_acc(kind, 0, fs*40)
            np.testing.assert_array_equal(signals[kind], b.generate_acc(kind, 0, fs*40))
            self.assertEqual(signals[kind].dtype, np.float32)
            self.assertTrue(np.isfinite(signals[kind]).all())
        self.assertFalse(np.array_equal(signals['EEG'], signals['PPG']))
        different = SyntheticPhysiology(seed=8, motion_level='strong').generate_acc('EEG', 0, 64*40)
        self.assertFalse(np.array_equal(signals['EEG'], different))

    def test_chunk_invariance_through_motion_and_rest_for_all_six_streams(self):
        for kind in SPECS:
            for acc in (False, True):
                fs = (ACC_SPECS if acc else SPECS)[kind][0]
                a = SyntheticPhysiology(seed=11, motion_level='moderate')
                b = SyntheticPhysiology(seed=11, motion_level='moderate')
                generate_a = a.generate_acc if acc else a.generate
                generate_b = b.generate_acc if acc else b.generate
                expected = generate_a(kind, 0, fs*80)
                actual = np.concatenate([generate_b(kind, start, min(71, fs*80-start))
                                         for start in range(0, fs*80, 71)])
                np.testing.assert_allclose(actual, expected, atol=2e-5, rtol=1e-6)

    def test_motion_component_is_the_difference_from_identical_clean_physiology(self):
        for kind, (fs, _) in SPECS.items():
            clean_model = SyntheticPhysiology(seed=9, artifact_level='none')
            moving = SyntheticPhysiology(seed=9, artifact_level='none', motion_level='strong')
            clean = clean_model.generate(kind, 0, fs*40)
            noisy = moving.generate(kind, 0, fs*40)
            artifact = moving.motion_artifact(kind, 0, fs*40)
            np.testing.assert_allclose(noisy, clean+artifact, atol=2e-5, rtol=1e-6)
            self.assertGreater(np.std(artifact), .03)
            np.testing.assert_array_equal(artifact[:int(MOTION_ONSETS[kind]*fs)], 0.)
            # Reconstruct the reference directly from the independently emitted ACC.
            rate = ACC_SPECS[kind][0]
            acc = moving.generate_acc(kind, 0, rate*40)
            t = np.arange(fs*40)/fs
            held = acc[np.floor(t*rate).astype(int)].astype(float)
            held[:, 2] -= float(np.float32(GRAVITY))
            np.testing.assert_array_equal(moving.motion.sampled_reference(kind, t), held)

    def test_nlms_reduces_error_after_quiet_movement_and_quiet_resumption(self):
        # Ground truth is the same seeded physiology, not the filtered output.
        # This exposed exploding weights when adaptation used near-zero ACC.
        for kind, (fs, names) in SPECS.items():
            with self.subTest(kind=kind):
                moving = SyntheticPhysiology(seed=2026, artifact_level='none', motion_level='strong')
                clean_model = SyntheticPhysiology(seed=2026, artifact_level='none')
                duration, rate = 80, ACC_SPECS[kind][0]
                t = np.arange(fs*duration)/fs
                raw = moving.generate(kind, 0, len(t))
                clean = clean_model.generate(kind, 0, len(t))
                acc = moving.generate_acc(kind, 0, rate*duration)
                acc_t = np.arange(len(acc))/rate
                canceller = MotionCanceller(fs, len(names), rate)
                output = []
                for second in range(duration):
                    canceller.append(acc[second*rate:(second+1)*rate], acc_t[second*rate:(second+1)*rate])
                    sl = slice(second*fs, (second+1)*fs)
                    output.append(canceller.process(raw[sl], t[sl]))
                output = np.concatenate(output)
                mask = (moving.motion.envelope(t, MOTION_ONSETS[kind]) > .75) & (t > MOTION_ONSETS[kind]+4)
                before = np.mean((raw[mask]-clean[mask])**2)
                after = np.mean((output[mask]-clean[mask])**2)
                self.assertLess(after, .5*before)  # At least 3 dB error-power reduction.
                self.assertTrue(np.isfinite(output).all())
                np.testing.assert_array_equal(output[:fs*7], raw[:fs*7])
                self.assertLess(np.max(np.abs(output)), 10*np.max(np.abs(raw)))

    def test_acc_order_empty_chunks_and_invalid_level(self):
        with self.assertRaises(ValueError):
            SyntheticPhysiology(motion_level='unknown')
        model = SyntheticPhysiology(motion_level='mild')
        self.assertEqual(model.generate_acc('PPG', 0, 0).shape, (0, 3))
        model.generate_acc('PPG', 0, 4)
        with self.assertRaises(ValueError):
            model.generate_acc('PPG', 0, 4)
        with self.assertRaises(ValueError):
            model.generate_acc('unknown', 0, 4)


if __name__ == '__main__':
    unittest.main()
