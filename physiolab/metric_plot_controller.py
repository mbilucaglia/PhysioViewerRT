"""Metric presentation ownership, separate from acquisition and Qt controls.

Metric histories are sparse observations (not raw frame tails). Their existing
pure smoothing/interpolation functions and normalization mathematics are reused.
Both backends consume the same prepared series and share command/view state.
"""
import time
import numpy as np
import pyqtgraph as pg
from .metric_catalog import metric_color
from .metric_display import prepare_metric_curve
from .vispy_metrics import VisPyMetricPlot


class PyQtGraphMetricPlot:
    def __init__(self,plot,keys):
        self.widget=self.plot=plot
        self.curves={}; self.markers={}
        for index,key in enumerate(keys):
            color=metric_color(index)
            self.curves[key]=plot.plot(name=f'{key[0]} / {key[1]}',
                pen=pg.mkPen(color,width=2),connect='finite')
            self.markers[key]=plot.plot(pen=None,symbol='o',symbolSize=5,
                symbolBrush=pg.mkBrush(color),symbolPen=None)

    @property
    def y_range(self): return tuple(self.plot.viewRange()[1])
    def set_y_auto(self,enabled): self.plot.enableAutoRange(axis='y',enable=enabled)
    def set_y_range(self,low,high): self.plot.setYRange(low,high,padding=0)
    def set_xrange(self,low,high): self.plot.setXRange(low,high,padding=0)
    def set_presentation_signature(self,signature): pass
    def refresh_axes(self): pass
    def set_series(self,key,x,y,mx,my,visible=True,show_line=True,show_markers=True):
        curve,markers=self.curves[key],self.markers[key]
        curve.setVisible(visible); markers.setVisible(visible and show_markers)
        if visible and show_line: curve.setData(x,y,connect='finite')
        else: curve.clear()
        if visible and show_markers: markers.setData(mx,my)
        else: markers.clear()
    def close(self): self.plot.clear()


class MetricPlotController:
    def __init__(self,state,settings):
        self.state=state; self.settings=settings
        self.backends={}; self.mode='pyqtgraph'
        self.origin=time.monotonic()
        self.duration=settings.default_view_seconds
        self.bounds=(-self.duration,0.)
        self.follow_live=True; self.paused=False
        self.dirty=True; self.generation=0
        self.auto_y=True; self.manual_y=None
        self.series={}; self.ruler_keys=set()
        self.frozen_history=None; self.paused_at=None

    def attach(self,plot): self.backends['pyqtgraph']=PyQtGraphMetricPlot(plot,self.state.keys)
    @property
    def gpu(self): return self.backends.get('vispy')
    @property
    def current(self): return self.backends[self.mode]

    def changed(self): self.generation+=1; self.dirty=True
    def data_changed(self):
        if not self.paused: self.dirty=True

    def reset(self,kind):
        if self.frozen_history is not None:
            for key in self.frozen_history:
                if key[0]==kind: self.frozen_history[key]=()
        self.changed()

    def set_backend(self,mode):
        if mode=='vispy' and mode not in self.backends:
            self.backends[mode]=VisPyMetricPlot(self.state.keys)
        self.mode=mode
        self.current.set_y_auto(self.auto_y)
        if not self.auto_y and self.manual_y is not None: self.current.set_y_range(*self.manual_y)
        self.current.set_xrange(*self.bounds)
        self.changed()

    def set_auto(self,enabled):
        if not enabled: self.manual_y=self.current.y_range
        self.auto_y=bool(enabled)
        for backend in self.backends.values(): backend.set_y_auto(enabled)

    def set_y_range(self,low,high):
        self.manual_y=(low,high)
        self.current.set_y_range(low,high)

    def zoom_y(self,factor):
        self.set_auto(False)
        low,high=self.current.y_range
        center,half=(low+high)/2.,(high-low)*factor/2.
        self.set_y_range(center-half,center+half)

    def fit_y(self):
        self.set_auto(False)
        values=[]; left,right=self.bounds
        for x,y,mx,my in self.series.values():
            for t,v in ((x,y),(mx,my)):
                values.extend(v[(t>=left)&(t<=right)&np.isfinite(v)])
        if values:
            low,high=float(np.min(values)),float(np.max(values)); pad=max(.1,(high-low)*.08)
            self.set_y_range(low-pad,high+pad)
        else: self.set_y_range(-1.,1.)

    def set_window(self,seconds):
        self.duration=self.settings.bounded_view_seconds(seconds)
        self.bounds=(self.bounds[1]-self.duration,self.bounds[1])
        self.follow_live=True; self.changed(); self.advance()

    def resume(self): self.follow_live=True; self.changed(); self.advance()
    def set_paused(self,paused):
        if bool(paused)==self.paused: return
        self.paused=bool(paused)
        self.frozen_history=({k:tuple(v) for k,v in self.state.history.items()} if paused else None)
        self.paused_at=time.monotonic() if paused else None
        self.changed()

    def manual_view(self,low,high):
        span=self.settings.bounded_view_seconds(high-low)
        low=high-span
        zoom=abs(span-self.duration)>max(.001,.001*self.duration)
        self.duration=span
        if self.follow_live and zoom:
            self.bounds=(self.bounds[1]-span,self.bounds[1])
        else:
            self.follow_live=False
            self.bounds=(low,high)
        self.changed(); self.advance()

    def advance(self):
        if self.follow_live and not self.paused:
            elapsed=time.monotonic()-self.origin
            self.bounds=(elapsed-self.duration,elapsed)
        if self.backends: self.current.set_xrange(*self.bounds)

    def refresh(self,*,normalization,references,smoothing,seconds,interpolation,markers,visible):
        if not self.backends: return
        backend=self.current
        backend.set_presentation_signature((normalization,smoothing,float(seconds),interpolation,
                                            bool(markers),self.generation))
        self.series={}; self.ruler_keys=set()
        now=self.paused_at if self.paused else time.monotonic()
        history=self.frozen_history if self.frozen_history is not None else self.state.history
        for key in self.state.keys:
            points=[(t,v) for t,v in history[key] if now-t<=self.settings.history_seconds]
            if key not in visible or not points:
                empty=np.empty(0); backend.set_series(key,empty,empty,empty,empty,visible=False)
                continue
            timestamps=np.array([t-self.origin for t,_ in points])
            values=[self.state.normalized_value(*key,v,normalization,references) for _,v in points]
            values=np.array([float(v) if v is not None else np.nan for v in values])
            series=prepare_metric_curve(timestamps,values,smoothing=smoothing,seconds=float(seconds),
                                        interpolation=interpolation,display_hz=20.,max_gap=1.1)
            self.series[key]=series
            if np.isfinite(series[3]).any(): self.ruler_keys.add(key)
            backend.set_series(key,*series,visible=True,show_line=interpolation!='none',
                               show_markers=markers or interpolation=='none')
        backend.refresh_axes(); self.dirty=False

    def set_units(self,unit,description):
        if self.mode=='vispy': self.current.set_amplitude_units(unit,description)

    def close(self):
        for backend in self.backends.values(): backend.close()
