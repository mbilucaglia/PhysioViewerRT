"""Display session invariants without Qt or an OpenGL context."""
import unittest
from types import SimpleNamespace

import numpy as np

from physiolab.raw_display_state import RawDisplayState
from physiolab.settings import ViewerSettings


class RawDisplayStateTests(unittest.TestCase):
    def append(self, state, kind, times):
        values = np.arange(len(times), dtype=float)[:, None]
        state.append(kind, values, values, ['channel'], 10., times, received_at=1.)
        return values

    def test_initial_centers_survive_drift_fit_and_display_channel_changes(self):
        state=RawDisplayState()
        x=np.arange(32,dtype=float).reshape(4,8)
        state.append('EEG',x,x,['C']*8,10.,100.+np.arange(4)/10.,center_trace='filtered')
        centers=state.recording_reference('EEG',8)[0].copy()
        state.append('EEG',x+100.,x+100.,['C']*8,10.,101.+np.arange(4)/10.)
        np.testing.assert_array_equal(state.recording_reference('EEG',4)[0],centers[:4])
        state.frames['EEG']=(None,None,None,centers,np.ones(8),['C']*8)
        state.request_autoscale('EEG')
        np.testing.assert_array_equal(state.recording_reference('EEG',8)[0],centers)
        state.reset('EEG')
        self.assertIsNone(state.recording_reference('EEG',8))
        state.append('EEG',x+100.,x+100.,['C']*8,10.,102.+np.arange(4)/10.)
        np.testing.assert_array_equal(state.recording_reference('EEG',8)[0],centers+100.)

    def test_hampel_delay_on_neighbors_cannot_stall_eeg_timebase(self):
        traces=[]
        for reduction in (False,True):
            state=RawDisplayState();sent={k:0 for k in ('EEG','PPG','EDA')};heads=[]
            for i in range(360):
                now=i/30.
                for kind,fs,phase in (('EEG',256.,0.),('PPG',128.,.02),('EDA',32.,.1)):
                    batch=max(0,int((now-phase)/.2))
                    end=max(0,int(batch*.2*fs)-(3 if reduction and kind!='EEG' else 0))
                    if end>sent[kind]:
                        times=100.+np.arange(sent[kind],end)/fs
                        values=np.zeros((len(times),1))
                        state.append(kind,values,values,[kind],fs,times,received_at=now)
                        sent[kind]=end
                state.advance(now)
                if now>3.:
                    heads.append(state.viewport('EEG')[1])
            traces.append(heads)
            self.assertTrue(np.all(np.diff(heads)>0.))
        np.testing.assert_allclose(traces[0],traces[1],atol=1e-12)

    def test_timebase_change_preserves_per_source_heads_and_startup_centers(self):
        state=RawDisplayState()
        for kind,end in (('EEG',1.),('PPG',.9),('EDA',.8)):
            times=100.+np.arange(0.,end,.1);values=np.ones((len(times),1))
            state.append(kind,values,values,[kind],10.,times,received_at=1.)
        state.advance(1.)
        before={kind:state.viewport(kind)[1] for kind in state.last_sample}
        references={kind:state.recording_reference(kind,1)[0].copy() for kind in state.last_sample}
        for duration in (10.,30.,5.,15.):
            state.set_window(duration)
            for kind in before:
                low,high=state.viewport(kind)
                self.assertEqual(high,before[kind]);self.assertEqual(high-low,duration)
                np.testing.assert_array_equal(state.recording_reference(kind,1)[0],references[kind])

    def test_frame_request_carries_each_source_timebase_head(self):
        from types import SimpleNamespace
        state=RawDisplayState()
        request=state.begin_frame({'EEG':SimpleNamespace(right=10.),'EDA':SimpleNamespace(right=9.9)},queued_at=1.)
        self.assertEqual(request.presentation_heads,{'EEG':10.,'EDA':9.9})

    def test_ingress_owns_samples_and_discards_duplicate_timestamps(self):
        state = RawDisplayState()
        source = self.append(state, 'EEG', [100., 100.1])
        source[:] = -1
        self.append(state, 'EEG', [100.1, 100.2])
        np.testing.assert_array_equal(state.history['EEG'][0][1][:, 0], [0, 1])
        np.testing.assert_allclose(state.history['EEG'][1][0], [100.2])
        self.assertEqual(state.origin, 100.)

    def test_window_change_rejects_obsolete_frame_and_frees_worker_slot(self):
        state = RawDisplayState()
        first = state.begin_frame({'EEG': object()}, queued_at=3.)
        self.assertIsNone(state.begin_frame({'EEG': object()}))
        state.set_window(10.)
        self.assertFalse(state.accepts(first.ticket, first.version))
        current = state.begin_frame({'EEG': object()})
        self.assertFalse(state.accepts(first.ticket, first.version))
        self.assertEqual(state.inflight_ticket, current.ticket)
        self.assertTrue(state.accepts(current.ticket, current.version))

    def test_shared_clock_uses_fresh_slowest_source_and_never_rewinds(self):
        state = RawDisplayState()
        state.origin = 100.
        state.clock = SimpleNamespace(advance=lambda now: 110.)
        state.last_sample = {'EEG': 110., 'EDA': 109.5, 'PPG': 100.}
        state.advance(1.)
        self.assertEqual(state.bounds, (4.5, 9.5))
        state.committed_head = 9.8
        state.advance(2.)
        np.testing.assert_allclose(state.bounds, (4.8, 9.8))

    def test_reset_retains_other_sources_and_last_reset_clears_clock(self):
        state = RawDisplayState()
        self.append(state, 'EEG', [100.])
        self.append(state, 'EDA', [101.])
        state.reset('EEG')
        self.assertTrue(state.history['EDA'])
        self.assertIsNotNone(state.origin)
        state.reset('EDA')
        self.assertIsNone(state.origin)
        self.assertIsNone(state.clock.head)
        self.assertIsNone(state.committed_head)

    def test_history_is_bounded_and_does_not_depend_on_plotting(self):
        state = RawDisplayState(ViewerSettings(history_seconds=5.))
        self.append(state, 'EEG', [100., 100.1])
        self.append(state, 'EEG', [106., 106.1])
        self.assertEqual(len(state.history['EEG']), 1)
        self.assertEqual(state.last_sample['EEG'], 106.1)

    def test_scale_changes_request_replay_and_autoscale_requires_data(self):
        state = RawDisplayState()
        state.request_autoscale('EEG')
        self.assertFalse(state.autoscale_requests)

        frame = (None, None, None, np.array([0.]), np.array([1.]), ['channel'])
        self.assertFalse(state.remember_frame('EEG', frame))
        self.assertFalse(state.remember_frame('EEG', frame))
        changed = (*frame[:4], np.array([2.]), frame[5])
        self.assertTrue(state.remember_frame('EEG', changed))
        state.request_autoscale('EEG')
        self.assertEqual(state.autoscale_requests, {'EEG'})
        state.reset('EEG')
        self.assertFalse(state.autoscale_requests)

    def test_plot_pause_freezes_view_but_not_acquisition_clock(self):
        state = RawDisplayState()
        state.origin = 100.
        state.clock = SimpleNamespace(advance=lambda now: 100.+now)
        original = state.bounds
        state.paused = True
        self.assertFalse(state.advance(5.))
        self.assertEqual(state.bounds, original)
        state.paused = False
        self.assertTrue(state.advance(5.1))
        np.testing.assert_allclose(state.bounds, (.1, 5.1))


if __name__ == '__main__':
    unittest.main()
