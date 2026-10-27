"""View state and source identities; history and numerical references live in SignalHistory."""
import time
import numpy as np
from .signal_history import SignalHistory
from .raw_timing import SmoothViewportClock
from .render_contracts import RawFrameRequest
from .display_units import DEFAULT_EEG_DISPLAY_STEP, ARBITRARY_UNIT
from .settings import DEFAULT_VIEWER_SETTINGS


class RawDisplayState:
    def __init__(self, settings=DEFAULT_VIEWER_SETTINGS, modalities=('EEG','EDA','PPG')):
        self.settings=settings
        self.signals=SignalHistory(settings.history_seconds,modalities)
        self.view_seconds=settings.default_view_seconds
        self.follow_live=True
        self.paused=False
        self.origin=None
        self.source_clocks={}
        self.source_bounds={}
        self.frozen_history=None
        self.display_scales={'EEG':DEFAULT_EEG_DISPLAY_STEP}
        self.units=dict.fromkeys(modalities,ARBITRARY_UNIT)
        self.frames={}
        self.autoscale_requests=set()
        self.center_requests=set()
        self.dirty=True
        self.epoch=self.ticket=0
        self.inflight={}
        self.interacting_until=0.
        self.last_received={}

    @property
    def history(self): return self.signals.chunks
    @property
    def initial_references(self): return self.signals.references
    @property
    def last_sample(self): return self.signals.last_sample
    @property
    def bounds(self):
        end=max((b[1] for b in self.source_bounds.values()),default=0.)
        return (end-self.view_seconds,end)

    def invalidate(self):
        self.epoch+=1
        self.inflight.clear()
        self.dirty=True

    def set_window(self,seconds):
        self.view_seconds=self.settings.bounded_view_seconds(seconds)
        self.source_bounds={k:(b[1]-self.view_seconds,b[1]) for k,b in self.source_bounds.items()}
        self.invalidate()

    def set_paused(self,paused):
        if bool(paused)==self.paused: return
        self.paused=bool(paused)
        self.frozen_history=({k:tuple(v) for k,v in self.history.items()} if paused else None)
        self.invalidate()

    def visible_history(self,kind):
        return self.frozen_history.get(kind,()) if self.frozen_history is not None else self.history[kind]

    def set_units(self,kind,scales,unit):
        self.display_scales[kind]=scales
        self.units[kind]=unit
        self.invalidate()

    def reset(self,kind):
        self.signals.reset(kind)
        self.frames.pop(kind,None)
        self.inflight.pop(kind,None)
        self.autoscale_requests.discard(kind)
        self.center_requests.discard(kind)
        self.source_clocks.pop(kind,None)
        self.source_bounds.pop(kind,None)
        self.last_received.pop(kind,None)
        if self.frozen_history is not None: self.frozen_history[kind]=()
        if not self.last_sample: self.origin=None
        self.dirty=True

    def append(self,kind,raw,filtered,names,fs,timestamps,received_at=None,center_trace='raw'):
        t=self.signals.append(kind,raw,filtered,names,fs,timestamps,center_trace)
        if t is None: return
        if self.origin is None: self.origin=float(t[0])
        received=time.monotonic() if received_at is None else float(received_at)
        self.last_received[kind]=received
        clock=self.source_clocks.setdefault(kind,SmoothViewportClock(self.settings.presentation_delay_seconds))
        clock.observe(float(t[-1]),received)
        if not self.paused: self.dirty=True

    def recording_reference(self,kind,count): return self.signals.reference(kind,count)
    def viewport(self,kind): return self.source_bounds.get(kind,(-self.view_seconds,0.))

    def advance(self,now):
        heads={kind:clock.advance(now) for kind,clock in self.source_clocks.items()}
        if self.origin is None or self.paused or not self.follow_live: return False
        changed=False
        for kind,head in heads.items():
            if head is None: continue
            end=min(head,self.last_sample[kind])-self.origin
            previous=self.source_bounds.get(kind)
            if previous is not None: end=max(end,previous[1])
            bounds=(end-self.view_seconds,end)
            changed |= previous!=bounds
            self.source_bounds[kind]=bounds
        return changed

    def request_autoscale(self,kind):
        if self.visible_history(kind):
            self.autoscale_requests.add(kind)
            self.invalidate()

    def request_center(self,kind):
        if self.visible_history(kind):
            self.center_requests.add(kind)
            self.invalidate()

    def begin_frame(self,sources,queued_at=None):
        sources={k:s for k,s in sources.items() if k not in self.inflight}
        if not sources: return None
        self.ticket+=1
        for kind in sources:
            self.inflight[kind]=(self.ticket,self.epoch,self.signals.generations[kind])
        return RawFrameRequest(self.ticket,self.epoch,sources,
            time.perf_counter() if queued_at is None else queued_at,
            presentation_heads={k:s.right for k,s in sources.items() if hasattr(s,'right')})

    def accepts(self,ticket,version,kind=None,source_generation=None):
        kinds=[kind] if kind else [k for k,v in self.inflight.items() if v[0]==ticket]
        accepted=False
        for k in kinds:
            expected=self.inflight.get(k)
            if expected is None or expected[:2]!=(ticket,version): continue
            self.inflight.pop(k)
            accepted |= (version==self.epoch and expected[2]==self.signals.generations[k]
                         and (source_generation is None or source_generation==expected[2]))
        return accepted

    def remember_frame(self,kind,frame):
        previous=self.frames.get(kind)
        changed=(previous is not None and (not np.array_equal(previous.centers,frame.centers)
                                          or not np.array_equal(previous.scales,frame.scales)))
        self.frames[kind]=frame
        return changed
