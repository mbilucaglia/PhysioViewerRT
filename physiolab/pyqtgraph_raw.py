"""pyqtgraph graphics ownership; same prepared-frame boundary as VisPy."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from .render_policy import RAW_DISPLAY_POLICY
from .modality_labels import modality_label


class PyQtGraphRawPlot:
    def __init__(self,kind,plot,history_seconds):
        self.kind,self.plot=kind,plot
        self.widget=plot
        self.curves=[]
        self.latest_sample_time=-np.inf
        self.channel_count=0
        self.history_seconds=history_seconds
        self._caption_duration=None

    def history_needs_replay(self,count,duration): return True
    def invalidate_history(self): pass  # Full-window backend; active drawing stays visible.

    def present(self,frame,view,fs):
        if view.duration!=self._caption_duration:
            self.plot.setTitle(f'{modality_label(self.kind)} — {view.duration:g} s view, '
                               f'{self.history_seconds/60:g} min history')
            self._caption_duration=view.duration
        if frame is None:
            self.reset()
            self.plot.setXRange(view.left,view.right,padding=0)
            return True
        n=frame.raw.shape[1]
        if len(self.curves)!=2*n:
            self.plot.clear(); self.curves=[]
            self.plot.enableAutoRange(axis='y',enable=False)
            self.plot.setYRange(*RAW_DISPLAY_POLICY.bounds(n),padding=0)
            self.plot.getAxis('left').setTicks([list(zip(RAW_DISPLAY_POLICY.offsets(n),map(str,frame.names)))])
            for i,name in enumerate(frame.names):
                color=pg.intColor(i,hues=max(n,3))
                for suffix,style in (('raw',Qt.PenStyle.SolidLine),('processed',Qt.PenStyle.DashLine)):
                    self.curves.append(self.plot.plot(name=f'{name} {suffix}',
                        pen=pg.mkPen(color,width=1,style=style),antialias=False))
        self.plot.setXRange(view.left,view.right,padding=0)
        # pyqtgraph's mask describes the edge STARTING at i; the contract's
        # mask describes the edge ENDING at i. Preserve real timestamp gaps.
        edges=(np.r_[frame.connect[1:],False] if frame.connect is not None else 'finite')
        for i in range(n):
            offset=RAW_DISPLAY_POLICY.channel_spacing*i
            for j,(values,enabled) in enumerate(((frame.raw,view.show_raw),(frame.filtered,view.show_filtered))):
                curve=self.curves[2*i+j]
                if enabled:
                    curve.setData(frame.times,offset+view.gain*(values[:,i]-offset),connect=edges)
                else: curve.clear()
        self.latest_sample_time=float(frame.times[-1]); self.channel_count=n
        return True

    def reset(self):
        self.plot.clear(); self.curves=[]; self.channel_count=0
        self.latest_sample_time=-np.inf

    def close(self): self.reset()
