"""One owner for plot commands, view transitions and frame validity.

The window supplies widget choices/visibility and displays signals. It neither
queries sample arrays nor knows how either backend stores or replays geometry.
"""
import time
import os
from dataclasses import replace
import numpy as np
from PySide6.QtCore import QObject, Signal
from .raw_display_state import RawDisplayState
from .raw_render_worker import RawRenderWorker
from .raw_snapshot import build_raw_source
from .render_contracts import ViewSpec
from .render_policy import RAW_DISPLAY_POLICY
from .amplitude_display import visible_gain
from .pyqtgraph_raw import PyQtGraphRawPlot
from .vispy_raw import VisPyRawPlot


class PlotController(QObject):
    frame_presented=Signal(str)
    gain_changed=Signal(str,float)
    status=Signal(str)

    def __init__(self,settings,performance,parent=None):
        super().__init__(parent)
        self.state=RawDisplayState(settings)
        self.performance=performance
        self.backends={'pyqtgraph':{},'vispy':{}}
        self.mode='pyqtgraph'
        self.gains=dict.fromkeys(self.state.history,1.)
        self.show_raw=self.show_filtered=True
        self.channel_limit=settings.default_eeg_display_channels
        self.visible=set()
        self.scheduler=RawRenderWorker(self)
        self.scheduler.frame_ready.connect(self.accept)
        self.scheduler.start()
        self.closed=False
        self.failures={}
        self.outcomes={}
        self.expired=set()
        self.presented_timing={}

    def register_plot(self,kind,plot):
        self.backends['pyqtgraph'][kind]=PyQtGraphRawPlot(kind,plot,self.state.settings.history_seconds)

    def change(self,*,replay=False):
        self.scheduler.cancel()
        self.state.invalidate()
        self.failures.clear()
        if replay:
            for backend in self.backends[self.mode].values(): backend.invalidate_history()

    def set_backend(self,mode):
        if mode==self.mode: return
        if mode=='vispy':
            for kind in self.state.history:
                if kind not in self.backends[mode]: self.backends[mode][kind]=VisPyRawPlot(kind)
        self.mode=mode
        self.change(replay=True)

    def set_visible(self,kinds):
        kinds=set(kinds)
        if kinds!=self.visible:
            self.visible=kinds
            self.change()

    def set_channels(self,count):
        if count!=self.channel_limit:
            self.channel_limit=int(count); self.change(replay=True)

    def set_traces(self,raw,filtered):
        self.show_raw,self.show_filtered=bool(raw),bool(filtered)
        self.change()

    def set_gain(self,kind,gain):
        self.gains[kind]=float(gain)
        self.change()

    def set_window(self,seconds):
        self.state.set_window(seconds)
        self.change(replay=True)

    def set_paused(self,paused):
        self.state.set_paused(paused)
        self.change()

    def follow_live(self):
        self.state.follow_live=True
        self.change()

    def manual_view(self,low,high):
        span=self.state.settings.bounded_view_seconds(high-low)
        low=high-span
        zoom=abs(span-self.state.view_seconds)>max(.001,.001*self.state.view_seconds)
        self.state.set_window(span)
        if not (self.state.follow_live and zoom):
            self.state.follow_live=False
            self.state.source_bounds={kind:(low,high) for kind in self.state.history}
        self.change(replay=True)

    def defer_interaction(self): self.state.interacting_until=time.monotonic()+.16

    def append(self,kind,raw,processed,names,fs,timestamps):
        self.expired.discard(kind)
        self.state.append(kind,raw,processed,names,fs,timestamps,
                          center_trace='filtered' if self.show_filtered else 'raw')

    def reset(self,kind):
        self.scheduler.cancel(kind)
        self.state.reset(kind)
        self.failures.pop(kind,None)
        self.outcomes.pop(kind,None)
        self.expired.discard(kind)
        self.presented_timing.pop(kind,None)
        for backends in self.backends.values():
            if kind in backends: backends[kind].reset()

    def set_units(self,kind,scale,unit):
        self.state.set_units(kind,scale,unit); self.change(replay=True)

    def center(self,kind):
        self.state.request_center(kind); self.change()

    def fit(self,kind):
        self.state.request_autoscale(kind); self.change()

    def tick(self,now=None):
        now=time.monotonic() if now is None else now
        if self.closed: return
        if self.state.advance(now): self.state.dirty=True
        if not self.state.paused and self.state.follow_live:
            for kind in self.visible:
                received=self.state.last_received.get(kind)
                if (received is not None and now-received>self.state.view_seconds
                        and kind not in self.expired):
                    self.scheduler.cancel(kind)
                    self.state.inflight.pop(kind,None)
                    self.empty_view(kind)
                    self.expired.add(kind)
        if not self.visible or not self.state.dirty or now<self.state.interacting_until: return
        self.draw()
        self.warm()

    def warm(self):
        """Link one spare channel pair per tick, without touching active data.

        Reserve only the displayed count in each of the two transactional banks.
        Linking all new shaders at a timebase commit causes long native stalls.
        """
        if self.mode!='vispy' or self.state.paused or os.environ.get('QT_QPA_PLATFORM')=='offscreen': return
        candidates=[]
        for kind in self.visible:
            chunks=self.state.history[kind]
            if not chunks: continue
            count=min(chunks[-1][1].shape[1],self.channel_limit if kind=='EEG' else RAW_DISPLAY_POLICY.max_single_channels)
            backend=self.backends[self.mode][kind]
            if backend.reserved_channel_count<2*count:
                candidates.append((count,kind,backend,chunks[-1][4]))
        for count,kind,backend,fs in sorted(candidates,key=lambda item:item[0]):
            start=time.perf_counter()
            if backend.warm_channels(2*count,self.state.view_seconds,fs):
                self.performance.measure('raw_warmup_'+kind,time.perf_counter()-start)
                break

    def empty_view(self,kind):
        state=self.state
        low,high=state.viewport(kind)
        view=ViewSpec(state.signals.generations[kind],state.epoch,low,high,
                      state.view_seconds,0,state.units[kind],self.gains[kind],
                      self.show_raw,self.show_filtered)
        self.backends[self.mode][kind].present(None,view,1.)
        state.center_requests.discard(kind)
        state.autoscale_requests.discard(kind)

    def draw(self):
        state=self.state
        if state.origin is None or self.closed: return
        sources={}
        state.dirty=False
        for kind in self.visible:
            if kind in state.inflight: continue
            if (kind in self.expired and state.follow_live and not state.paused
                    or self.failures.get(kind,0)>=3): continue
            chunks=state.visible_history(kind)
            if not chunks:
                self.empty_view(kind); continue
            count=min(chunks[-1][1].shape[1],self.channel_limit if kind=='EEG' else RAW_DISPLAY_POLICY.max_single_channels)
            ref=state.recording_reference(kind,count)
            if ref is None: continue
            backend=self.backends[self.mode][kind]
            low,high=state.viewport(kind)
            command=('center' if kind in state.center_requests else 'fit' if kind in state.autoscale_requests else None)
            gpu=self.mode=='vispy'
            replay=backend.history_needs_replay(count,state.view_seconds)
            if gpu and command is None: low=high-RAW_DISPLAY_POLICY.history_cycles*state.view_seconds
            latest=backend.latest_sample_time
            source=build_raw_source(chunks,left=low,right=high,origin=state.origin,
                reference=ref,vispy=gpu and command is None,
                latest=latest if np.isfinite(latest) else None,
                replay_history=replay or command is not None,sweep_seconds=state.view_seconds,
                max_channels=count,shared_scale=state.display_scales.get(kind),
                fit_traces=kind in ('PPG','EDA'),center_trace='filtered' if self.show_filtered else 'raw')
            if source is not None:
                sources[kind]=replace(source,source_generation=state.signals.generations[kind],
                    coverage='full' if replay or command or not gpu else 'incremental',
                    unit=state.units[kind],available_at=state.last_received.get(kind),command=command,
                    max_points=max(128,min(RAW_DISPLAY_POLICY.max_points,backend.widget.width()*2)))
            else: self.empty_view(kind)
        request=state.begin_frame(sources)
        if request is not None: self.scheduler.submit(request)

    def accept(self,response):
        if self.closed: return
        state=self.state
        for kind,frame in response.frames.items():
            source=response.sources.get(kind)
            if source is None: continue
            if not state.accepts(response.ticket,response.version,kind,source.source_generation):
                self.performance.count('raw_stale_'+kind); continue
            self.performance.measure('raw_prepare_'+kind,response.prepare_ms/1000.)
            if response.started_at is not None:
                self.performance.measure('raw_queue_age_'+kind,response.started_at-response.queued_at)
            outcome=response.outcomes[kind]
            self.outcomes[kind]=outcome
            self.performance.count('raw_'+outcome.status+'_'+kind)
            if outcome.status!='ready':
                if outcome.error: self.status.emit(f'{kind} plot: {outcome.error}')
                if outcome.status=='failed':
                    attempts=self.failures.get(kind,0)+1
                    self.failures[kind]=attempts
                    if attempts<3:
                        state.dirty=True
                        continue
                else:
                    # A buffered head may lie inside a real source gap. Empty
                    # coverage is availability, not a preparation failure.
                    self.failures.pop(kind,None)
                if outcome.status!='cancelled':
                    state.center_requests.discard(kind)
                    state.autoscale_requests.discard(kind)
                    if outcome.status=='no_data': self.empty_view(kind)
                continue
            if kind not in self.visible: state.dirty=True; continue
            if source.command=='center':
                old_centers,old_scales=state.initial_references[kind]
                centers=old_centers.copy(); n=frame.raw.shape[1]
                if centers.ndim==2: centers[:,:n]=frame.centers
                else: centers[:n]=frame.centers
                state.signals.set_reference(kind,centers,old_scales)
                state.center_requests.discard(kind)
                self.change(replay=True)
                continue
            if source.command=='fit':
                gain=visible_gain(frame,state.view_seconds,self.show_raw,self.show_filtered,source.right)
                state.autoscale_requests.discard(kind)
                if gain is not None:
                    self.gains[kind]=gain; self.gain_changed.emit(kind,gain)
            state.remember_frame(kind,frame)
            view=ViewSpec(source.source_generation,response.version,source.right-state.view_seconds,
                          source.right,state.view_seconds,frame.raw.shape[1],source.unit,
                          self.gains[kind],self.show_raw,self.show_filtered)
            start=time.perf_counter()
            try:
                ready=self.backends[self.mode][kind].present(frame,view,source.chunks[-1][4])
            except Exception as exc:
                self.status.emit(f'{kind} drawing failed: {type(exc).__name__}: {exc}')
                attempts=self.failures.get(kind,0)+1
                self.failures[kind]=attempts
                if attempts<3:
                    self.backends[self.mode][kind].invalidate_history()
                    state.dirty=True
                continue
            self.performance.measure('raw_backend_'+kind,time.perf_counter()-start)
            if not ready: state.dirty=True
            else:
                self.failures.pop(kind,None)
                self.presented_timing[kind]=(response.queued_at,response.ready_at,time.perf_counter())
                self.frame_presented.emit(kind)

    def close(self):
        self.closed=True; self.scheduler.stop()
        for backends in self.backends.values():
            for backend in backends.values(): backend.close()
