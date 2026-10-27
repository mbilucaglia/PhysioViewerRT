"""Time-stable sweep rings: no full redrawing of historical samples."""
import unittest
import numpy as np
from physiolab.incremental_sweep import SweepRing


class SweepRingTests(unittest.TestCase):
    def test_small_timestamp_jitter_cannot_remove_every_signal_segment(self):
        for fs in (32., 128., 256.):
            ring = SweepRing(5., fs)
            index = np.arange(int(fs))
            times = index/fs + np.where(index % 2 == 0, 1e-6, -1e-6)
            ring.append(times, np.sin(times))
            drawn = np.any(ring.positions != -10., axis=(1, 2))
            self.assertEqual(np.count_nonzero(drawn), len(times)-1)
            np.testing.assert_allclose(ring.positions[1, :, 0], times[:2]/5.)

    def test_half_bin_phase_jitter_does_not_create_false_gaps(self):
        for fs in (32.,128.,256.):
            ring=SweepRing(5.,fs)
            index=np.arange(int(fs))
            times=(index+.5)/fs+np.where(index%2==0,1e-6,-1e-6)
            ring.append(times,np.sin(times))
            self.assertEqual(np.count_nonzero(np.any(ring.positions!=-10.,axis=(1,2))),len(times)-1)
            before=ring.positions.copy()
            self.assertEqual(ring.append(times,np.sin(times)),[])
            np.testing.assert_array_equal(before,ring.positions)

    def test_only_one_segment_changes_when_one_sample_arrives(self):
        ring = SweepRing(duration=5., rate=10.)
        initial = ring.append([.1, .2, .3], [1., 2., 3.])
        self.assertLessEqual(len(initial), 6)
        before = ring.positions.copy()
        newer = ring.append([.1, .2, .3, .4], [1., 2., 3., 4.])
        self.assertEqual({s for s, _ in newer}, {4})
        np.testing.assert_array_equal(before[1:4], ring.positions[1:4])
        self.assertEqual(ring.last_time, .4)

    def test_idempotent_replayed_snapshots(self):
        ring = SweepRing(5., 10.)
        ring.append([.1, .2, .3], [1., 2., 3.])
        first = ring.positions.copy()
        self.assertEqual(ring.append([.1, .2, .3], [1., 2., 3.]), [])
        np.testing.assert_array_equal(first, ring.positions)

    def test_wrap_updates_only_next_positions_without_diagonal(self):
        ring = SweepRing(1., 10.)
        ring.append(np.arange(0., 1., .1), np.ones(10))
        changes = ring.append([1., 1.1], [2., 3.])
        self.assertLessEqual(len(changes), 4)
        for _, segment in changes:
            if not np.all(segment == -10):
                self.assertGreaterEqual(segment[1, 0], segment[0, 0])
        self.assertGreater(ring.stamps[0], .9)

    def test_missing_samples_cannot_be_connected(self):
        ring = SweepRing(5., 10., max_gap=.25)
        ring.append([.1, .2, 1.0], [1., 2., 3.])
        self.assertTrue(np.all(ring.positions[10] == -10.))

    def test_next_old_segment_stays_visible_until_its_replacement_arrives(self):
        ring = SweepRing(5., 100.)
        times = np.arange(500) / 100.
        ring.append(times, np.sin(times))
        before = ring.positions.copy()
        incoming = 5. + np.arange(124)/100.
        ring.append(incoming, np.cos(incoming))
        # Each old segment retains its own old endpoints; no mixed-cycle
        # diagonal or premature blank space is introduced after the cursor.
        np.testing.assert_array_equal(ring.positions[124:], before[124:])
        self.assertAlmostEqual(ring.positions[123, 1, 0], 1.23/5.)
        self.assertAlmostEqual(ring.positions[125, 0, 0], 1.24/5.)
        replay = SweepRing(5., 100.)
        replay.append(np.r_[times, incoming], np.r_[np.sin(times), np.cos(incoming)])
        np.testing.assert_array_equal(replay.positions, ring.positions)

    def test_dimensions_and_empty_history(self):
        ring = SweepRing(5., 20.)
        self.assertEqual(ring.capacity, 100)
        self.assertEqual(ring.append([], []), [])
        with self.assertRaises(ValueError):
            ring.append([0., 1.], [2.])

    def test_batch_replay_matches_samplewise_updates_across_wraps_and_gaps(self):
        rng = np.random.default_rng(24)
        batch_ring, sample_ring = SweepRing(1., 32.), SweepRing(1., 32.)
        for batch in range(20):
            times = batch * .5 + np.arange(80) / 64.
            times[10:13] = [np.nan, times[9], times[7]]
            values = rng.normal(size=len(times))
            values[5] = np.nan
            batch_ring.append(times, values)
            for stamp, value in zip(times, values):
                sample_ring.append([stamp], [value])
            np.testing.assert_array_equal(batch_ring.positions, sample_ring.positions)
            np.testing.assert_array_equal(batch_ring.identities, sample_ring.identities)
            self.assertEqual(batch_ring.last_time, sample_ring.last_time)


class SparseMarkerTests(unittest.TestCase):
    def test_jittered_sparse_markers_expire_after_cursor_passes_old_cycle(self):
        from unittest.mock import patch
        from physiolab.incremental_sweep import IncrementalSweepLayer
        from reference_geometry import metric_sweep_points

        class Visual:
            def __init__(self, capacity, color, mode, parent):
                self.positions = np.full((capacity, 2), -10., dtype=np.float32)

            def patch(self, updates):
                for index, vertices in updates:
                    self.positions[index] = vertices[0]

        with patch('physiolab.incremental_sweep._incremental_visual_class', return_value=Visual):
            layer = IncrementalSweepLayer(None, 1., 20., '#000000', mode='points')
        times, values = [], []
        for cycle in range(5):
            jitter = .01 if cycle % 2 == 0 else .06
            for stamp in np.arange(cycle+jitter, cycle+.95, .1):
                times.append(stamp)
                values.append(stamp * .3)
                layer.append(times, values)
                actual = layer.visual.positions
                actual = actual[actual[:, 0] >= 0]
                expected = metric_sweep_points(times, values, 1., stamp)
                actual = actual[np.argsort(actual[:, 1])]
                expected = expected[np.argsort(expected[:, 1])]
                np.testing.assert_allclose(actual, expected, atol=1e-6)



if __name__ == '__main__':
    unittest.main()
