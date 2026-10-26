import unittest
from types import SimpleNamespace
import numpy as np
from physiolab.peripheral_runtime import peripheral_runtime_state
from physiolab.processing import Processor

class PeripheralRuntimeTests(unittest.TestCase):
    def test_real_state_pulse_expiry_stale_and_pending(self):
        w=SimpleNamespace(active=True,preprocessing={},reduction_feedback=(None,None,0.,True))
        self.assertEqual(peripheral_runtime_state(None,10.)[0],'idle')
        self.assertEqual(peripheral_runtime_state(w,10.)[0],'off')
        w.preprocessing={'artifact_reduction':'wavelet'}
        w.reduction_feedback=(None,None,3.,True)
        self.assertIn('3.0/8 s',peripheral_runtime_state(w,10.)[1])
        w.reduction_feedback=(10.,None,8.,False)
        self.assertEqual(peripheral_runtime_state(w,10.)[0],'monitoring')
        w.reduction_feedback=(10.,10.,8.,False)
        self.assertEqual(peripheral_runtime_state(w,10.4)[0],'correcting')
        self.assertEqual(peripheral_runtime_state(w,10.6)[0],'monitoring')
        self.assertEqual(peripheral_runtime_state(w,13.)[0],'waiting')
        self.assertIn('updating',peripheral_runtime_state(w,10.,True)[1])
        w.reduction_feedback=(10.,None,.5,True)
        self.assertIn('buffering',peripheral_runtime_state(w,10.)[1])
        w.active=False
        self.assertEqual(peripheral_runtime_state(w,10.)[0],'idle')

    def test_processor_reports_reducer_changes_only_not_filter_changes(self):
        x=np.ones((32,1))*3.
        p=Processor('PPG',32.,1,['PPG'],preprocessing={'notch':False,'artifact_reduction':'hampel'})
        p.push(x)
        self.assertFalse(p.last_reduction_changed)
        self.assertFalse(np.allclose(p.last_raw_chunk,p.last_filtered_chunk))
        spike=x.copy();spike[10]=12.
        p.push(spike)
        self.assertTrue(p.last_reduction_changed)
        p.push(x)
        self.assertFalse(p.last_reduction_changed)
        w=Processor('EDA',32.,1,['SC'],preprocessing={'notch':False,'artifact_reduction':'wavelet'})
        w.push(np.ones((256,1))*3.)
        self.assertFalse(w.last_reduction_changed)
