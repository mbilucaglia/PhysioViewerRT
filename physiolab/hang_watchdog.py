"""Native-timer Qt event-loop hang diagnostics.

The original Python watchdog could itself be starved when the UI was
unresponsive. faulthandler.dump_traceback_later instead uses a native
watchdog thread; refreshing its deadline from the Qt event loop means
a Python thread starvation is captured without relying on the GIL.
"""
import faulthandler
import os
from pathlib import Path
import time


class GuiHangWatchdog:
    def __init__(self, enabled=None, path=None, timeout=5., poll_interval=.5):
        self.enabled = (os.environ.get('PHYSIOLAB_PROFILE') == '1'
                        if enabled is None else bool(enabled))
        self.path = Path(path) if path else Path.home() / 'PhysioViewerRT-hangs.log'
        self.timeout = float(timeout)
        # Rate-limit native timer refresh, even when Qt renders at 30 FPS.
        self.poll_interval = max(.01, min(float(poll_interval), self.timeout / 3))
        self._last_arm = 0.0
        self._file = None
        self._running = False

    def _arm(self):
        if self._file is None:
            return
        faulthandler.dump_traceback_later(
            self.timeout, repeat=False, file=self._file, exit=False
        )
        self._last_arm = time.monotonic()

    def beat(self):
        if self._running and time.monotonic() - self._last_arm >= self.poll_interval:
            self._arm()

    def start(self):
        if not self.enabled or self._running:
            return
        try:
            # Keep this file descriptor open until the native timer is cancelled.
            # Create early to expose configuration errors before the hang.
            self._file = self.path.open('a', encoding='utf-8')
        except OSError:
            self.enabled = False
            return
        self._running = True
        self._arm()

    def stop(self):
        if not self._running:
            return
        faulthandler.cancel_dump_traceback_later()
        self._running = False
        self._file.close()
        self._file = None
