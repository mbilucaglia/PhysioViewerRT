"""Native cursor-to-trace alignment, including a delayed modality."""
import os,time,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication
from physiolab.vispy_raw import VisPyRawPlot

class WaveformPlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

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
