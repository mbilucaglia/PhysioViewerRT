"""Bounded source-scoped preparation, cancellation and terminal outcomes.

Each source has two execution lanes: one obsolete call may finish while its
replacement runs. Pending work coalesces to one snapshot per source. Pure work
checks a cancellation token between bounded operations. Stop never waits for an
uncooperative numerical call; workers hold no widgets or graphics resources.
"""
import threading
import time
from dataclasses import replace
from PySide6.QtCore import QObject, Signal
from .raw_render import prepare_raw_window
from .render_contracts import RawFrameRequest, RawFrameResult, FrameOutcome, PreparationCancelled


class RawRenderWorker(QObject):
    frame_ready=Signal(object)

    def __init__(self,parent=None):
        super().__init__(parent)
        self._condition=threading.Condition()
        self._pending={}
        self._active={}
        self._threads=[]
        self._stopping=False
        self._started=False

    def start(self): self._started=True
    def isRunning(self): return self._started and not self._stopping

    def _result(self,request,kind,source,status,frame=None,error=None,started=None):
        now=time.perf_counter()
        return RawFrameResult(request.ticket,request.version,{kind:frame},
            (now-started)*1000. if started else 0.,request.queued_at,now,
            presentation_heads={kind:source.right},outcomes={kind:FrameOutcome(status,error)},
            sources={kind:source},started_at=started)

    def submit(self,request):
        if not isinstance(request,RawFrameRequest): raise TypeError('RawFrameRequest required')
        with self._condition:
            if self._stopping: return
            for kind,source in request.sources.items():
                identity=(request.version,source.source_generation)
                for old,token in self._active.get(kind,[]):
                    if old!=identity: token.set()
                previous=self._pending.pop(kind,None)
                if previous:
                    old_request,old_source=previous
                    self.frame_ready.emit(self._result(old_request,kind,old_source,'cancelled'))
                self._pending[kind]=(request,source)
                if kind not in self._active:
                    self._active[kind]=[]
                    for lane in range(2):
                        thread=threading.Thread(target=self._run,args=(kind,),daemon=True,
                                                name=f'prepare-{kind}-{lane}')
                        self._threads.append(thread); thread.start()
            self._condition.notify_all()

    def cancel(self,kind=None):
        with self._condition:
            kinds=[kind] if kind else list(self._active)
            for k in kinds:
                for _,token in self._active.get(k,[]): token.set()
                pending=self._pending.pop(k,None)
                if pending:
                    request,source=pending
                    self.frame_ready.emit(self._result(request,k,source,'cancelled'))
            self._condition.notify_all()

    def stop(self):
        with self._condition:
            self._stopping=True
            for jobs in self._active.values():
                for _,token in jobs: token.set()
            self._pending.clear()
            self._condition.notify_all()
        deadline=time.monotonic()+.1
        for thread in self._threads: thread.join(max(0.,deadline-time.monotonic()))

    def _run(self,kind):
        while True:
            with self._condition:
                while kind not in self._pending and not self._stopping: self._condition.wait()
                if self._stopping: return
                request,source=self._pending.pop(kind)
                token=threading.Event()
                entry=((request.version,source.source_generation),token)
                self._active[kind].append(entry)
            started=time.perf_counter(); frame=None; error=None
            try:
                frame=prepare_raw_window(source.chunks,source.left,source.right,source.origin,
                    None if source.command=='center' else source.reference,
                    decimation_span=source.decimation_span,max_channels=source.max_channels,
                    shared_scale=source.shared_scale,fit_traces=source.fit_traces,
                    center_trace=source.center_trace,cancelled=token.is_set,max_points=source.max_points)
                status='ready' if frame is not None else 'no_data'
            except PreparationCancelled:
                status='cancelled'
            except Exception as exc:
                status='failed'; error=f'{type(exc).__name__}: {exc}'
            with self._condition:
                self._active[kind].remove(entry)
                if self._stopping: return
                if token.is_set(): status='cancelled'; frame=None
                self.frame_ready.emit(self._result(request,kind,source,status,frame,error,started))
