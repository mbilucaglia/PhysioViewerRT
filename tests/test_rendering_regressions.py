"""Behavioral reproductions of R2–R7, initially failing at bcd8d35."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
import numpy as np
from physiolab.raw_render import prepare_raw_window
from physiolab.raw_display_state import RawDisplayState
from physiolab.incremental_sweep import SweepRing
from physiolab.vispy_raw import VisPyRawPlot


class RenderingRegressions(unittest.TestCase):
    def test_absent_source_does_not_reallocate_retained_gpu_banks(self):
        plot=VisPyRawPlot.__new__(VisPyRawPlot)
        plot.engine=Mock(); plot.canvas=Mock()
        layers=[Mock() for _ in range(64)]
        plot._layer_pool={'raw':layers[:32],'filtered':layers[32:]}
        plot.layers={k:list(v) for k,v in plot._layer_pool.items()}
        plot._pending_layers=None
        for _ in range(10): plot.reset()
        for layer in layers:
            layer.reconfigure.assert_not_called()
            self.assertFalse(layer.visual.visible)
        self.assertEqual(plot.channel_count,0)

    def test_narrow_raw_and_cleaned_extrema_survive_long_window(self):
        fs=256.; t=np.arange(60*256)/fs
        x=np.zeros((len(t),1)); y=x.copy(); x[1]=100.; y[3]=-70.
        frame=prepare_raw_window([(t,x,y,['C'],fs)],0.,60.,0.,
            reference=(np.zeros(1),np.ones(1)),decimation_span=60.)
        self.assertEqual(float(frame[1].max()),100.)
        self.assertEqual(float(frame[2].min()),-70.)

    def test_gap_expires_old_line_slots(self):
        ring=SweepRing(5.,10.)
        ring.append(np.arange(50)/10.,np.ones(50))
        ring.append([20.,20.1],[2.,2.])
        drawn=np.any(ring.positions!=-10.,axis=(1,2))
        self.assertFalse(np.any(drawn & (ring.stamps<15.1)))

    def test_live_gap_recovers_without_slewing_through_missing_seconds(self):
        state=RawDisplayState(); x=np.zeros((10,1))
        state.append('PPG',x,x,['P'],10.,100.+np.arange(10)/10.,received_at=0.)
        for i in range(61): state.advance(i/30.)
        state.append('PPG',x,x,['P'],10.,120.+np.arange(10)/10.,received_at=20.)
        state.advance(20.)
        self.assertLessEqual(120.9-state.origin-state.viewport('PPG')[1],.5)

    def test_reference_independent_of_packetization(self):
        x=np.arange(10.)[:,None]; t=np.arange(10)/10.
        states=[]
        for splits in ((10,),(2,8),(1,1,1,1,1,1,1,1,1,1)):
            state=RawDisplayState(); start=0
            for size in splits:
                end=start+size
                state.append('EEG',x[start:end],x[start:end],['C'],10.,t[start:end])
                start=end
            states.append(state.recording_reference('EEG',1))
        for reference in states[1:]:
            np.testing.assert_array_equal(reference[0],states[0][0])
            np.testing.assert_array_equal(reference[1],states[0][1])

    def test_replacement_can_be_submitted_before_obsolete_completion(self):
        state=RawDisplayState()
        first=state.begin_frame({'EEG':SimpleNamespace(right=1.)})
        state.set_window(30.)
        replacement=state.begin_frame({'PPG':SimpleNamespace(right=1.)})
        self.assertIsNotNone(replacement)
        self.assertFalse(state.accepts(first.ticket,first.version))

    def test_staging_does_not_hide_or_reconfigure_active_layers(self):
        class Layer:
            def __init__(self,*args,**kwargs):
                self.visual=SimpleNamespace(visible=True); self.resets=0
            def reconfigure(self,*args,**kwargs): self.resets+=1
            def close(self): pass
        plot=VisPyRawPlot.__new__(VisPyRawPlot)
        plot.view=SimpleNamespace(scene=None)
        plot.layers={k:[Layer() for _ in range(4)] for k in ('raw','filtered')}
        plot._layer_pool={k:list(v) for k,v in plot.layers.items()}
        plot._configuration=(4,5.,128.)
        plot._pending_layers=plot._pending_configuration=None
        with patch('physiolab.incremental_sweep.IncrementalSweepLayer',Layer):
            pending,ready=plot._ensure_layers(8,5.,128.)
        self.assertFalse(ready)
        for key in plot.layers:
            for layer in plot.layers[key]:
                self.assertTrue(layer.visual.visible)
                self.assertEqual(layer.resets,0)
                self.assertNotIn(layer,pending[key])

    def test_extrema_reach_gpu_geometry_with_original_timestamps_and_gap_mask(self):
        fs=256.; t=np.arange(60*256)/fs
        x=np.zeros((len(t),1)); y=x.copy()
        x[-101]=100.; y[-103]=-70.
        # A source gap must remain disconnected after visual reduction.
        keep=(t<45.)|(t>47.)
        t,x,y=t[keep],x[keep],y[keep]
        frame=prepare_raw_window([(t,x,y,['C'],fs)],0.,60.,0.,
            reference=(np.zeros(1),np.ones(1)),decimation_span=60.)
        for values,expected in ((frame.raw,100.),(frame.filtered,-70.)):
            ring=SweepRing(30.,fs)
            ring.append(frame.times,values[:,0],connect=frame.connect)
            drawn=ring.positions[np.any(ring.positions!=-10.,axis=(1,2))]
            self.assertIn(expected,drawn[:,:,1])
            gap=(drawn[:,0,0]<.5)&(drawn[:,1,0]>.57)
            self.assertFalse(gap.any())
        np.testing.assert_array_equal(frame.times,t[np.searchsorted(t,frame.times)])

    def test_history_is_readonly_and_bounded_for_large_and_tiny_packets(self):
        from physiolab.settings import ViewerSettings
        state=RawDisplayState(ViewerSettings(history_seconds=5.))
        t=np.arange(10000)/100.; x=t[:,None]
        state.append('EEG',x,x,['C'],100.,t)
        self.assertLessEqual(sum(len(c[0]) for c in state.history['EEG']),501)
        with self.assertRaises(ValueError): state.history['EEG'][0][1][0]=0.
        for i in range(10000,12000):
            state.append('EEG',[[i]],[[i]],['C'],100.,[i/100.])
        self.assertLessEqual(sum(len(c[0]) for c in state.history['EEG']),501)
        self.assertLessEqual(len(state.history['EEG']),3)

    def test_pause_keeps_authoritative_history_after_live_retention_expires(self):
        from physiolab.settings import ViewerSettings
        state=RawDisplayState(ViewerSettings(history_seconds=5.))
        t=np.arange(50)/10.; x=t[:,None]
        state.append('PPG',x,x,['P'],10.,t,received_at=0.)
        state.advance(0.); state.set_paused(True)
        frozen=state.visible_history('PPG')
        state.append('PPG',x+100,x+100,['P'],10.,t+100.,received_at=100.)
        self.assertIs(state.visible_history('PPG'),frozen)
        self.assertEqual(float(frozen[0][0][0]),0.)
        state.set_paused(False); state.advance(100.)
        self.assertGreater(state.viewport('PPG')[1],100.)

    def test_restart_invalidates_only_that_source(self):
        state=RawDisplayState()
        request=state.begin_frame({'EEG':SimpleNamespace(right=1.),'PPG':SimpleNamespace(right=1.)})
        state.reset('EEG')
        self.assertFalse(state.accepts(request.ticket,request.version,'EEG',0))
        self.assertTrue(state.accepts(request.ticket,request.version,'PPG',0))
