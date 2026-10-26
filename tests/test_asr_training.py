"""Adaptive quality screening and accepted-data progress without wall-clock waits."""
import unittest
import numpy as np
from physiolab.asr_training import ASRTrainingAccumulator

class ASRTrainingTests(unittest.TestCase):
    def setUp(self):
        self.fs = 128.
        self.monitor = ASRTrainingAccumulator(self.fs, ['F3', 'F4', 'O1', 'O2'])
        self.rng = np.random.default_rng(32)

    def push(self, second, amplitude=1., flat=False):
        data = self.rng.normal(size=(128, 4))*amplitude
        if flat:
            data[:, 0] = 1.
        times = second+np.arange(128)/128.
        self.monitor.push(data, data, times, now=second+1.)
        return self.monitor.status(now=second+1.)

    def test_bad_windows_do_not_advance_accepted_time_and_clean_windows_accumulate(self):
        self.assertEqual(self.push(0)['state'], 'warming')
        self.push(1)
        self.assertEqual(self.push(2)['accepted_seconds'], 1.)
        self.assertEqual(self.push(3, flat=True)['state'], 'bad')
        self.assertEqual(self.monitor.status(4.)['accepted_seconds'], 1.)
        self.assertEqual(self.push(4, amplitude=100.)['state'], 'movement')
        self.assertEqual(self.push(5)['accepted_seconds'], 2.)
        snapshot = self.monitor.snapshot({'fs':128., 'channels':['F3','F4','O1','O2']})
        self.assertEqual(snapshot['data'].shape, (256, 4))
        self.assertEqual(snapshot['accepted_window_samples'], [128,128])
        self.assertGreater(np.max(np.diff(snapshot['timestamps'])), 1.)

    def test_dropout_and_stale_signal_are_explicit(self):
        self.push(0)
        self.assertEqual(self.push(3)['state'], 'bad')
        self.assertEqual(self.monitor.status(6.)['state'], 'bad')
        self.assertIn('No fresh EEG', self.monitor.status(6.)['reason'])

    def test_adaptive_capture_needs_more_elapsed_time_when_motion_is_rejected(self):
        for second in range(72):
            self.push(second, amplitude=100. if 10 <= second < 20 else 1.)
        status = self.monitor.status(72.)
        self.assertEqual(status['recorded_seconds'], 72.)
        self.assertEqual(status['accepted_seconds'], 60.)
        self.assertEqual(status['rejected_seconds'], 12.)

    def test_bounded_storage_and_transport_chunk_splitting(self):
        self.monitor = ASRTrainingAccumulator(128., ['F3','F4','O1','O2'], maximum_seconds=3.)
        for second in range(8):
            x = self.rng.normal(size=(128,4))
            for start in (0, 64):
                times = second+np.arange(start,start+64)/128.
                self.monitor.push(x[start:start+64], x[start:start+64], times, now=second+1.)
        self.assertEqual(self.monitor.status(8.)['accepted_seconds'], 3.)
