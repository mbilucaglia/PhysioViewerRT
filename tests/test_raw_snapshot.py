"""Pure RAW viewport selection tests, no Qt dependencies."""
import unittest
import numpy as np
from physiolab.raw_snapshot import build_raw_source


class RawSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.chunks = tuple(
            (np.array([100. + i, 100. + i + .5]),
             np.zeros((2, 16)), np.zeros((2, 16)),
             [f'C{x}' for x in range(16)], 2.)
            for i in range(10)
        )

    def test_selects_only_intersecting_chunks(self):
        result = build_raw_source(
            self.chunks, left=5., right=7., origin=100.,
            max_channels=16)
        self.assertEqual(len(result.chunks), 3)
        self.assertEqual(result.max_channels, 16)
        self.assertIs(result.chunks[0], self.chunks[5])

    def test_first_gpu_frame_is_bounded_to_live_tail(self):
        result = build_raw_source(
            self.chunks, left=0., right=9.5, origin=100.,
            vispy=True, sweep_seconds=5.)
        self.assertAlmostEqual(result.left, 9.15)
        self.assertEqual(result.decimation_span, 10.)

    def test_incremental_gpu_frame_uses_last_sample(self):
        ref = (np.zeros(8), np.ones(8))
        result = build_raw_source(
            self.chunks, left=0., right=9.5, origin=100.,
            reference=ref, vispy=True, latest=8.7)
        self.assertAlmostEqual(result.left, 8.6)
        self.assertIs(result.reference, ref)

    def test_missing_view_has_no_frame(self):
        self.assertIsNone(build_raw_source(
            self.chunks, left=30., right=40., origin=100.))


if __name__ == '__main__':
    unittest.main()
