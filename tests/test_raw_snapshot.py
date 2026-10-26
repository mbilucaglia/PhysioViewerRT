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

    def test_new_gpu_layers_can_replay_two_cycle_history(self):
        result = build_raw_source(
            self.chunks, left=0., right=9.5, origin=100.,
            vispy=True, replay_history=True, sweep_seconds=5.)
        self.assertEqual(result.left, 0.)
        self.assertGreater(len(result.chunks), 1)

    def test_missing_view_has_no_frame(self):
        self.assertIsNone(build_raw_source(
            self.chunks, left=30., right=40., origin=100.))


class FixedPeripheralSnapshotTests(unittest.TestCase):
    def test_latched_peripheral_reference_uses_new_tail_not_full_window(self):
        import numpy as np
        from physiolab.raw_snapshot import build_raw_source
        times=np.arange(1000)/100.
        values=np.ones((1000,1))
        chunks=((times,values,values,['PPG'],100.),)
        source=build_raw_source(chunks,left=0.,right=10.,origin=0.,
            vispy=True,latest=9.5,reference=(np.ones((2,1)),np.ones(1)),fit_traces=True)
        self.assertAlmostEqual(source.left,9.4)
        replay=build_raw_source(chunks,left=0.,right=10.,origin=0.,vispy=True,
            latest=9.5,reference=(np.ones((2,1)),np.ones(1)),fit_traces=True,replay_history=True)
        self.assertEqual(replay.left,0.)


if __name__ == '__main__':
    unittest.main()
