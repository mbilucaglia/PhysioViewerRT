"""Latest-only background worker for raw waveform preparation.

The worker operates exclusively on immutable NumPy chunk snapshots.
Only the Qt GUI thread creates/updates pyqtgraph items.
"""
import threading
import time
from PySide6.QtCore import QThread, Signal

from .raw_render import prepare_raw_window
from .render_contracts import RawFrameRequest


class RawRenderWorker(QThread):
    frame_ready = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._condition = threading.Condition()
        self._pending = None
        self._stopping = False

    def submit(self, request):
        """Replace an obsolete pending frame; never queue unbounded work."""
        with self._condition:
            if self._stopping:
                return
            self._pending = request
            self._condition.notify()

    def stop(self):
        with self._condition:
            self._stopping = True
            self._pending = None
            self._condition.notify()
        self.wait()

    def run(self):
        while True:
            with self._condition:
                while self._pending is None and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                request = self._pending
                self._pending = None
            started = time.perf_counter()
            frames = {}
            if not isinstance(request, RawFrameRequest):
                continue
            for kind, source in request.sources.items():
                try:
                    frames[kind] = prepare_raw_window(
                        source.chunks, source.left, source.right,
                        source.origin, source.reference,
                        decimation_span=source.decimation_span,
                        max_channels=source.max_channels,
                        max_points=source.max_points
                    )
                except (ValueError, IndexError) as exc:
                    frames[kind] = None
            self.frame_ready.emit({
                'ticket': request.ticket,
                'prepare_ms': (time.perf_counter() - started) * 1000.,
                'version': request.version,
                'frames': frames,
                'queued_at': request.queued_at,
                'ready_at': time.perf_counter(),
            })
