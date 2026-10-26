"""Runtime ASR feedback must report execution, not checkbox intent."""
import unittest
from types import SimpleNamespace
from physiolab.asr_runtime import asr_runtime_state

class ASRRuntimeTests(unittest.TestCase):
    def test_off_pending_bypass_waiting_active_and_stale(self):
        w = SimpleNamespace(active=True, asr_status='ASR disabled',
            eeg_asr_model=None, asr_last_processed_at=None)
        self.assertEqual(asr_runtime_state(None, 10.)[0], 'idle')
        self.assertEqual(asr_runtime_state(w, 10.)[0], 'off')
        self.assertEqual(asr_runtime_state(w, 10., True)[0], 'waiting')
        w.eeg_asr_model = SimpleNamespace(model_id='test')
        self.assertEqual(asr_runtime_state(w, 10.)[0], 'waiting')
        w.asr_last_processed_at = 9.9
        self.assertEqual(asr_runtime_state(w, 10.)[0], 'on')
        self.assertEqual(asr_runtime_state(w, 13.)[0], 'waiting')
        w.asr_status = 'ASR bypassed after processing error: test'
        self.assertEqual(asr_runtime_state(w, 10.)[0], 'bypassed')
        w.active = False
        self.assertEqual(asr_runtime_state(w, 10.)[0], 'idle')
