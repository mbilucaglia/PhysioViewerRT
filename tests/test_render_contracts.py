"""Regression checks for the immutable RAW worker request protocol."""
import unittest
from dataclasses import FrozenInstanceError

from physiolab.render_contracts import RawFrameRequest, RawSourceRequest


class RenderContractTests(unittest.TestCase):
    def test_typed_snapshot_keeps_ordered_chunks_and_parameters(self):
        chunk = object()
        source = RawSourceRequest(
            chunks=(chunk,), left=1., right=2., origin=100.,
            decimation_span=10., max_channels=32)
        request = RawFrameRequest(
            ticket=7, version=3, sources={'EEG': source}, queued_at=1.5)
        self.assertIs(request.sources['EEG'].chunks[0], chunk)
        self.assertEqual(request.sources['EEG'].max_channels, 32)
        self.assertEqual(request.ticket, 7)
        with self.assertRaises(FrozenInstanceError):
            source.left = 0.


if __name__ == '__main__':
    unittest.main()
