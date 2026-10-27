"""Native command and scheduler regressions from the architectural audit."""
import os
import time
import unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from physiolab.raw_render_worker import RawRenderWorker
from physiolab.render_contracts import RawFrameRequest, RawSourceRequest
from physiolab.gui import MainWindow

app=QApplication.instance() or QApplication([])

def pump(predicate, timeout=3.):
    end=time.perf_counter()+timeout
    while time.perf_counter()<end:
        app.processEvents()
        if predicate(): return True
        time.sleep(.002)
    return False


class RenderingRegressions(unittest.TestCase):
    def test_fragmented_peak_replay_bounds_gpu_upload_calls_without_changing_geometry(self):
        from unittest.mock import Mock
        from physiolab.incremental_sweep import IncrementalSweepLayer
        layer=IncrementalSweepLayer(None,5.,256.,'#000000')
        original=layer.visual._buffer
        layer.visual._buffer=Mock()
        try:
            times=np.arange(0,1280,3)/256.
            values=np.sin(times)
            connect=np.ones(len(times),dtype=bool); connect[0]=False
            layer.append(times,values,connect)
            calls=layer.visual._buffer.set_subdata.call_args_list
            self.assertLessEqual(len(calls),8)
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0].kwargs['offset'],0)
            np.testing.assert_array_equal(calls[0].args[0],layer.ring.positions.reshape(-1,2))
        finally:
            layer.visual._buffer=original
            layer.close()

    def test_manual_and_command_windows_are_bounded_before_backend_allocation(self):
        from unittest.mock import Mock
        from physiolab.plot_controller import PlotController
        from physiolab.metric_plot_controller import MetricPlotController
        from physiolab.settings import DEFAULT_VIEWER_SETTINGS as settings
        raw=PlotController(settings,Mock())
        metric=MetricPlotController(Mock(),settings)
        try:
            raw.state.follow_live=False; metric.follow_live=False
            raw.manual_view(-1e9,10.)
            metric.manual_view(-1e9,10.)
            self.assertEqual(raw.state.view_seconds,settings.history_seconds)
            self.assertEqual(raw.state.viewport('PPG'),(-290.,10.))
            self.assertEqual(metric.duration,settings.history_seconds)
            self.assertEqual(metric.bounds,(-290.,10.))
            raw.set_window(1e9); metric.set_window(1e9)
            self.assertEqual(raw.state.view_seconds,settings.history_seconds)
            self.assertEqual(metric.duration,settings.history_seconds)
        finally: raw.close(); metric.close()

    def test_source_restart_recovers_after_capped_failures(self):
        with patch.object(MainWindow,'refresh',lambda self:None): w=MainWindow()
        try:
            w.show(); w.tabs.setCurrentWidget(w.raw_page)
            t=np.arange(128)/128.; x=np.sin(t)[:,None]
            with patch('physiolab.raw_render_worker.prepare_raw_window',side_effect=RuntimeError('persistent')):
                w.receive('PPG',x,x,['P'],None,128.,t)
                self.assertTrue(pump(lambda:w.raw_controller.failures.get('PPG',0)>=3))
            w.reset_stream_display('PPG')
            w.receive('PPG',x,x,['P'],None,128.,t+10.)
            self.assertTrue(pump(lambda:'PPG' in w.raw_display.frames))
            self.assertNotIn('PPG',w.raw_controller.failures)
        finally: w.close(); app.processEvents()

    def test_empty_view_updates_axes_and_expired_history_remains_inspectable(self):
        with patch.object(MainWindow,'refresh',lambda self:None): w=MainWindow()
        try:
            w.show(); w.tabs.setCurrentWidget(w.raw_page)
            w.raw_renderer_choice.setCurrentIndex(0)
            t=np.arange(640)/128.; x=np.sin(t)[:,None]
            w.receive('PPG',x,x,['P'],None,128.,t)
            self.assertTrue(pump(lambda:len(w.curves['PPG'])==2))
            w.raw_controller.tick(time.monotonic()+20.)
            self.assertIn('PPG',w.raw_controller.expired)
            w.set_plot_paused('raw',True)
            self.assertTrue(pump(lambda:len(w.curves['PPG'])==2))
            w.raw_controller.manual_view(100.,105.)
            self.assertTrue(pump(lambda:len(w.curves['PPG'])==0))
            np.testing.assert_allclose(w.plots['PPG'].viewRange()[0],[100.,105.])
            w.raw_time_window.setCurrentIndex(w.raw_time_window.findData(10))
            self.assertTrue(pump(lambda:abs(np.diff(w.plots['PPG'].viewRange()[0])[0]-10)<1e-6))
            self.assertIn('10 s view',w.plots['PPG'].getPlotItem().titleLabel.text)
        finally: w.close(); app.processEvents()

    def test_paused_metric_timebase_replays_frozen_series(self):
        with patch.object(MainWindow,'refresh',lambda self:None): w=MainWindow()
        try:
            w.show(); w.tabs.setTabEnabled(w.tabs.indexOf(w.metrics_page),True)
            w.tabs.setCurrentWidget(w.metrics_page)
            now=time.monotonic(); w.metric_controller.origin=now-3.
            w.metric_state.history['EEG','AWI'].extend([(now-2.,0.),(now-1.,1.),(now,2.)])
            w.refresh_metric_plot(); w.set_plot_paused('metrics',True)
            for mode in (0,1,0):
                w.metric_renderer_choice.setCurrentIndex(mode)
                w.metric_time_window.setCurrentIndex(w.metric_time_window.findData(10))
                self.assertTrue(pump(lambda:not w.metric_dirty))
                self.assertIn(('EEG','AWI'),w.metric_controller.series)
                if mode==1:
                    self.assertTrue(np.isfinite(w.vispy_metric_plot._layers['EEG','AWI'][0].ring.last_time))
                else: self.assertIsNotNone(w.metric_curves['EEG','AWI'].getData()[0])
        finally: w.close(); app.processEvents()

    def test_paused_metric_mouse_zoom_updates_frozen_bounds(self):
        with patch.object(MainWindow,'refresh',lambda self:None): w=MainWindow()
        try:
            controller=w.metric_controller
            controller.bounds=(10.,15.)
            controller.duration=5.
            controller.set_paused(True)
            controller.manual_view(11.,14.)
            self.assertEqual(controller.duration,3.)
            self.assertEqual(controller.bounds,(12.,15.))
            self.assertTrue(controller.follow_live)
        finally: w.close(); app.processEvents()

    def test_empty_frames_during_short_packet_gap_restart_do_not_disable_source(self):
        with patch.object(MainWindow,'refresh',lambda self:None): w=MainWindow()
        try:
            controller=w.raw_controller
            controller.set_backend('pyqtgraph')
            controller.set_visible({'PPG'})
            state=controller.state
            state.follow_live=False
            x=np.ones((10,1)); t=np.arange(10)/10.
            controller.append('PPG',x,x,['P'],10.,t)
            # The new short packet shares an immutable block with old data.
            # Its first sample is still ahead of the buffered display head.
            controller.append('PPG',x[:2],x[:2],['P'],10.,20.+t[:2])
            state.source_bounds['PPG']=(15.,19.85)
            for _ in range(4):
                state.dirty=True; controller.draw()
                self.assertTrue(pump(lambda:not state.inflight))
            self.assertEqual(controller.failures.get('PPG',0),0)
            controller.append('PPG',x,x,['P'],10.,20.2+t)
            state.source_bounds['PPG']=(16.,21.)
            controller.draw()
            self.assertTrue(pump(lambda:'PPG' in state.frames))
            self.assertGreater(state.frames['PPG'].times[-1],20.)
        finally: w.close(); app.processEvents()

    def test_failure_has_terminal_outcome_and_next_job_recovers(self):
        worker=RawRenderWorker(); received=[]
        worker.frame_ready.connect(received.append)
        source=RawSourceRequest((),0.,1.,0.)
        try:
            worker.start()
            with patch('physiolab.raw_render_worker.prepare_raw_window',side_effect=RuntimeError('injected')):
                worker.submit(RawFrameRequest(1,0,{'PPG':source},time.perf_counter()))
                self.assertTrue(pump(lambda:len(received)==1))
            self.assertEqual(received[0].outcomes['PPG'].status,'failed')
            self.assertIn('injected',received[0].outcomes['PPG'].error)
            worker.submit(RawFrameRequest(2,0,{'PPG':source},time.perf_counter()))
            self.assertTrue(pump(lambda:len(received)==2))
            self.assertEqual(received[-1].outcomes['PPG'].status,'no_data')
        finally: worker.stop()

    def test_replacement_bypasses_obsolete_slow_job_and_stop_is_bounded(self):
        import threading
        entered=threading.Event(); release=threading.Event()
        def prepare(chunks,*args,**kwargs):
            if chunks==('slow',): entered.set(); release.wait(2.)
            return None
        worker=RawRenderWorker(); received=[]
        worker.frame_ready.connect(received.append)
        try:
            with patch('physiolab.raw_render_worker.prepare_raw_window',side_effect=prepare):
                worker.start()
                worker.submit(RawFrameRequest(1,0,{'EEG':RawSourceRequest(('slow',),0,1,0)},time.perf_counter()))
                self.assertTrue(entered.wait(.5))
                worker.submit(RawFrameRequest(2,1,{'EEG':RawSourceRequest(('fast',),0,1,0)},time.perf_counter()))
                self.assertTrue(pump(lambda:any(r.ticket==2 for r in received),.3))
                start=time.perf_counter(); worker.stop()
                self.assertLess(time.perf_counter()-start,.25)
                release.set()
        finally: release.set(); worker.stop()

    def test_center_uses_full_visible_history_and_paused_failure_retries(self):
        from physiolab.raw_render import prepare_raw_window
        with patch.object(MainWindow,'refresh',lambda self:None): w=MainWindow()
        try:
            w.resize(1440,900); w.tabs.setCurrentWidget(w.raw_page); w.show()
            t=np.arange(640)/128.; x=(10.+np.cos(2*np.pi*t))[:,None]
            w.receive('PPG',x,x,['P'],None,128.,t)
            self.assertTrue(pump(lambda:'PPG' in w.raw_display.frames))
            w.set_plot_paused('raw',True)
            low,high=w.raw_display.viewport('PPG')
            expected=np.median(x[(t>=low)&(t<=high)])
            gain=w.raw_vertical_gains['PPG'].value()
            calls=[]
            def fail_once(*args,**kwargs):
                calls.append(1)
                if len(calls)==1: raise RuntimeError('once')
                return prepare_raw_window(*args,**kwargs)
            with patch('physiolab.raw_render_worker.prepare_raw_window',side_effect=fail_once):
                w.center_raw('PPG')
                self.assertTrue(pump(lambda: 'PPG' not in w.raw_display.center_requests))
            self.assertGreaterEqual(len(calls),2)
            np.testing.assert_allclose(w.raw_display.initial_references['PPG'][0],expected)
            self.assertEqual(w.raw_vertical_gains['PPG'].value(),gain)
        finally: w.close(); app.processEvents()

    def test_healthy_source_completes_before_delayed_neighbor(self):
        def prepare(chunks,*args,**kwargs):
            if chunks==('slow',): time.sleep(.3)
            return None
        worker=RawRenderWorker(); received=[]
        worker.frame_ready.connect(lambda r:received.append((time.perf_counter(),r)))
        try:
            with patch('physiolab.raw_render_worker.prepare_raw_window',side_effect=prepare):
                worker.start(); start=time.perf_counter()
                worker.submit(RawFrameRequest(1,0,{
                    'EEG':RawSourceRequest(('slow',),0.,1.,0.),
                    'PPG':RawSourceRequest(('fast',),0.,1.,0.)},start))
                self.assertTrue(pump(lambda:any('PPG' in r.frames for _,r in received)))
                ppg=next(at for at,r in received if 'PPG' in r.frames)
                self.assertLess(ppg-start,.2)
        finally: worker.stop()

    def test_paused_backend_and_timebase_commands_repaint(self):
        with patch.object(MainWindow,'refresh',lambda self:None): w=MainWindow()
        try:
            w.resize(1440,900); w.tabs.setCurrentWidget(w.raw_page); w.show()
            t=np.arange(640)/128.; x=(10.+np.cos(2*np.pi*t))[:,None]
            w.receive('PPG',x,x,['PPG'],None,128.,t)
            self.assertTrue(pump(lambda:'PPG' in w.raw_display.frames))
            w.set_plot_paused('raw',True)
            w.raw_renderer_choice.setCurrentIndex(0)
            self.assertTrue(pump(lambda:len(w.curves['PPG'])==2))
            w.raw_time_window.setCurrentIndex(w.raw_time_window.findData(10))
            self.assertTrue(pump(lambda:abs(np.diff(w.plots['PPG'].viewRange()[0])[0]-10)<1e-6))
        finally: w.close(); app.processEvents()
