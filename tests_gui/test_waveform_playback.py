"""Native cursor-to-trace alignment, including a delayed modality."""
import os,time,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication
from physiolab.vispy_raw import VisPyRawPlot

class WaveformPlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_timebase_handoff_keeps_source_heads_and_initial_centering(self):
        from unittest.mock import patch
        from pylsl import local_clock
        from physiolab.gui import MainWindow
        with patch.object(MainWindow,'refresh',lambda self:None):w=MainWindow()
        try:
            w.tabs.setCurrentWidget(w.raw_page)
            w.resize(1440,900);w.show();self.app.processEvents();w.timer.stop()
            origin=local_clock()-3.
            for kind,delay,fs in (('EEG',0.,256.),('PPG',.023,128.),('EDA',.094,32.)):
                times=origin+np.arange(round(3*fs))/fs-delay
                values=np.sin(np.arange(len(times))/10.)[:,None]
                w.receive(kind,values,values,['signal'],None,fs,times)
            references={k:w.raw_display.recording_reference(k,1)[0].copy() for k in ('EEG','PPG','EDA')}
            heads=[]
            with patch.object(w.raw_render_worker,'submit',side_effect=lambda request:heads.append(request)):
                for duration in (10,30,5,15):
                    w.raw_display.inflight.clear()
                    w.raw_time_window.setCurrentIndex(w.raw_time_window.findData(duration))
                    w.update_raw_xranges();w.draw()
                    self.assertTrue(heads)
                    request=heads[-1]
                    for kind in ('EEG','PPG','EDA'):
                        self.assertAlmostEqual(request.presentation_heads[kind],request.sources[kind].right)
                        np.testing.assert_array_equal(w.raw_display.recording_reference(kind,1)[0],references[kind])
        finally:
            w.close();self.app.processEvents()

    @unittest.skipUnless(os.environ.get('QT_QPA_PLATFORM')=='windows','Native OpenGL pixel verification')
    def test_slow_stream_cursor_is_at_drawn_endpoint_and_history_does_not_pan(self):
        for kind in ('EEG','PPG','EDA'):
            plot=VisPyRawPlot(kind)
            try:
                plot.widget.resize(900,500);plot.widget.show()
                for _ in range(4):self.app.processEvents();time.sleep(.01)
                times=np.arange(1.,3.,1/32.)
                values=np.zeros((len(times),1))
                plot.set_frame((times,values,values,None,None,('channel',)),0.,5.,show_raw=False,sweep_head=4.,nominal_fs=32.)
                for _ in range(3):self.app.processEvents()
                geometry=plot.layers['filtered'][0].ring.positions.copy()
                plot.set_sweep_head(4.8)
                pixels=plot.canvas.render()
                blue=(pixels[:,:,2]>150)&(pixels[:,:,0]<60)&(pixels[:,:,1]>60)&(pixels[:,:,1]<160)
                column=int(np.argmax(blue.sum(axis=0)))
                expected=times[-1]/5.*pixels.shape[1]
                self.assertLessEqual(abs(column-expected),2.)
                np.testing.assert_array_equal(plot.layers['filtered'][0].ring.positions,geometry)
            finally:
                plot.widget.close();plot.close();self.app.processEvents()
