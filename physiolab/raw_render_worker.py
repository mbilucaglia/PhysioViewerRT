"""Latest-only background worker for raw waveform preparation.

The worker operates exclusively on immutable NumPy chunk snapshots.
Only the Qt GUI thread creates/updates pyqtgraph items.
"""
import threading
from PySide6.QtCore import QThread, Signal

from .raw_render import prepare_raw_window


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
            frames = {}
            for kind, (chunks, left, right, origin, reference) in request['sources'].items():
                try:
                    frames[kind] = prepare_raw_window(
                        chunks, left, right, origin, reference
                    )
                except (ValueError, IndexError) as exc:
                    frames[kind] = None
            self.frame_ready.emit({
                'ticket': request['ticket'],
                'version': request['version'],
                'frames': frames,
            })
