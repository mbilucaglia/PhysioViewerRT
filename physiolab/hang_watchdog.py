"""Independent GUI hang detector for opt-in performance diagnostics.

A daemon monitor observes a heartbeat maintained by Qt's timer. On a long
stall it writes Python stacks of all threads, independently of the GUI timer.
This is diagnostic: native Qt/C++ stacks require separate OS-level tools.
"""
import faulthandler
import os
from pathlib import Path
import threading
import time


class GuiHangWatchdog:
    def __init__(self, enabled=None, path=None, timeout=5., poll_interval=.5):
        self.enabled = (os.environ.get('PHYSIOLAB_PROFILE') == '1'
                        if enabled is None else bool(enabled))
        self.path = Path(path) if path else Path.home() / 'PhysioViewerRT-hangs.log'
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self._heartbeat = time.monotonic()
        self._halt = threading.Event()
        self._thread = None
        self._reported = False

    def beat(self):
        self._heartbeat = time.monotonic()
        self._reported = False

    def start(self):
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._monitor, name='PhysioViewerRT-GUI-watchdog',
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._halt.set()
        if self._thread is not None:
            self._thread.join(timeout=1.)

    def _monitor(self):
        while not self._halt.wait(self.poll_interval):
            age = time.monotonic() - self._heartbeat
            if age < self.timeout or self._reported:
                continue
            self._reported = True
            try:
                with self.path.open('a', encoding='utf-8') as log:
                    log.write(
                        f'\nGUI HEARTBEAT STALLED for {age:.2f}s; '
                        f'wall_time={time.strftime("%Y-%m-%d %H:%M:%S")}\n'
                    )
                    log.flush()
                    faulthandler.dump_traceback(file=log, all_threads=True)
                    log.flush()
            except OSError:
                # Logging failures must not interfere with acquisition.
                pass
