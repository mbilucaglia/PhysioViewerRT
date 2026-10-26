"""Native pixel alignment and retained GPU geometry for peripheral DC drift."""
import os,time,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PySide6.QtWidgets import QApplication
from physiolab.vispy_raw import VisPyRawPlot
from physiolab.render_policy import RAW_DISPLAY_POLICY

class WaveformPlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    @unittest.skipUnless(os.environ.get('QT_QPA_PLATFORM')=='windows','Native OpenGL pixel verification')
    def test_drifting_peripheral_trace_stays_at_its_label_without_rewriting_samples(self):
        for kind in ('EDA','PPG'):
            plot=VisPyRawPlot(kind)
            try:
                plot.widget.resize(900,500);plot.widget.show()
                for _ in range(4):self.app.processEvents();time.sleep(.01)
                t=(np.arange(128)+.5)/32.
                values=np.ones((128,1))*1.5
                original=values.copy()
                plot.set_frame((t,values,values,None,None,('SCL',)),0.,5.,show_raw=False,nominal_fs=32.)
                layer=plot.layers['filtered'][0]
                geometry=layer.ring.positions.copy()
                for gain in (1.,2.,.5):
                    plot.set_vertical_gain(gain)
                    for _ in range(3):self.app.processEvents()
                    pixels=plot.canvas.render()
                    black=np.max(pixels[:,:,:3],axis=2)<80
                    row=int(np.argmax(black.sum(axis=1)))
                    expected=plot.engine.label_gutter.label_center(0)
                    self.assertLessEqual(abs(row-expected),1.5)
                    np.testing.assert_array_equal(layer.ring.positions,geometry)
                np.testing.assert_array_equal(values,original)
            finally:
                plot.widget.close();plot.close();self.app.processEvents()
