import unittest
import numpy as np

from physiolab.calibration_session import CalibrationSession


class CalibrationSessionTests(unittest.TestCase):
    def session(self, modalities=('EEG',)):
        return CalibrationSession('BSL', {
            kind: {'channels': ['One'], 'fs': 2., 'preprocessing': {},
                   'start_lsl_timestamp': 10.}
            for kind in modalities}, deadline=100.)

    def test_capture_filters_boundary_and_copies_source_arrays(self):
        session = self.session()
        data = np.arange(4.)[:, None]
        times = np.array([9., 10., 10.5, 11.])
        session.append('EEG', data, times, ['One'], 2., 99.)
        data[:] = -1
        times[:] = -1
        result = session.finish(minimum_seconds=1.)['EEG']
        np.testing.assert_array_equal(result['data'][:, 0], [2., 3.])
        np.testing.assert_array_equal(result['timestamps'], [10.5, 11.])

    def test_missing_expected_modality_is_rejected(self):
        session = self.session(('EEG', 'EDA'))
        session.append('EEG', np.ones((2, 1)), [11., 11.5], ['One'], 2., 99.)
        with self.assertRaisesRegex(ValueError, 'EDA: no samples'):
            session.finish(minimum_seconds=1.)

    def test_deadline_and_short_capture_are_rejected_at_finish(self):
        session = self.session()
        session.append('EEG', np.ones((2, 1)), [11., 11.5], ['One'], 2., 101.)
        with self.assertRaisesRegex(ValueError, 'no samples'):
            session.finish()
        session.append('EEG', np.ones((2, 1)), [11., 11.5], ['One'], 2., 100.)
        with self.assertRaisesRegex(ValueError, 'only 1.0 s'):
            session.finish()

    def test_metadata_changes_invalidate_complete_capture(self):
        session = self.session()
        session.append('EEG', np.ones((2, 1)), [11., 11.5], ['Wrong'], 2., 99.)
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            session.finish(minimum_seconds=0.)

    def test_capture_owns_lists_and_does_not_mutate_metadata(self):
        metadata = {'EEG': {'channels': ['One'], 'fs': 2.}}
        session = CalibrationSession('EYC', metadata, 100.)
        session.append('EEG', np.ones((2, 1)), [11., 11.5], ['One'], 2., 99.)
        self.assertNotIn('chunks', metadata['EEG'])
        self.assertEqual(len(session.streams['EEG']['chunks']), 1)
