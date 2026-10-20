"""Check EEG multi-select and single-channel EDA/PPG source slicing."""
import unittest
import numpy as np
from physiolab.channel_selection import validated_indices, select_chunk


class StreamChannelSelectionTests(unittest.TestCase):
    def test_eeg_multiple_channels_preserve_lsl_source_order(self):
        indices = validated_indices([3, 0, 2], 4, 'EEG')
        self.assertEqual(indices, [0, 2, 3])
        chunk = np.arange(20).reshape(5, 4)
        np.testing.assert_array_equal(select_chunk(chunk, indices), chunk[:, [0, 2, 3]])

    def test_eda_ppg_exactly_one(self):
        for kind in ('EDA', 'PPG'):
            self.assertEqual(validated_indices([2], 4, kind), [2])
            for bad in ([], [0, 1]):
                with self.subTest(kind=kind, selection=bad):
                    with self.assertRaises(ValueError):
                        validated_indices(bad, 4, kind)

    def test_eeg_no_selection_and_invalid_indices(self):
        for indices in ([], [0, 0], [-1], [9]):
            with self.subTest(indices=indices):
                with self.assertRaises(ValueError):
                    validated_indices(indices, 4, 'EEG')

    def test_independent_modality_assignments_can_share_one_stream(self):
        chunk = np.array([[11, 22, 33], [44, 55, 66]])
        eeg = select_chunk(chunk, validated_indices([0, 1], 3, 'EEG'))
        eda = select_chunk(chunk, validated_indices([2], 3, 'EDA'))
        ppg = select_chunk(chunk, validated_indices([1], 3, 'PPG'))
        self.assertEqual(eeg.shape, (2, 2))
        self.assertEqual(eda.shape, (2, 1))
        self.assertEqual(ppg.shape, (2, 1))


if __name__ == '__main__':
    unittest.main()
