"""Time-stable sweep rings: no full redrawing of historical samples."""
import unittest
import numpy as np
from physiolab.incremental_sweep import SweepRing


class SweepRingTests(unittest.TestCase):
    def test_only_two_slots_change_when_one_sample_arrives(self):
        ring = SweepRing(duration=5., rate=10.)
        initial = ring.append([.1, .2, .3], [1., 2., 3.])
        self.assertLessEqual(len(initial), 6)
        before = ring.positions.copy()
        newer = ring.append([.1, .2, .3, .4], [1., 2., 3., 4.])
        self.assertEqual({s for s, _ in newer}, {4, 5})
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

    def test_dimensions_and_empty_history(self):
        ring = SweepRing(5., 20.)
        self.assertEqual(ring.capacity, 100)
        self.assertEqual(ring.append([], []), [])
        with self.assertRaises(ValueError):
            ring.append([0., 1.], [2.])


if __name__ == '__main__':
    unittest.main()
