import unittest
import numpy as np

from physiolab.acquisition_contracts import AcquisitionChunk


class AcquisitionChunkTests(unittest.TestCase):
    def test_named_fields_preserve_existing_unpacking_and_indexing(self):
        raw, filtered, times = np.ones((2, 1)), np.zeros((2, 1)), np.array([1., 2.])
        chunk = AcquisitionChunk(raw, filtered, ['Ch1'], None, 1., times, 3.)
        self.assertEqual(len(chunk), 7)
        self.assertIs(chunk[0], raw)
        self.assertIs(chunk.filtered, filtered)
        self.assertIs(chunk.timestamps, times)
        self.assertEqual(chunk.acquired_at, 3.)
        self.assertEqual(chunk._fields, ('raw', 'filtered', 'names', 'metric', 'fs',
                                         'timestamps', 'acquired_at'))
