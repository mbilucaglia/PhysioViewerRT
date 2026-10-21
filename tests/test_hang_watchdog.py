"""Regression coverage for native timer GUI hang diagnostics."""
import tempfile
import time
import unittest
from pathlib import Path

from physiolab.hang_watchdog import GuiHangWatchdog


class GuiWatchdogTests(unittest.TestCase):
    def test_disabled_watchdog_creates_no_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hangs.log'
            watchdog = GuiHangWatchdog(enabled=False, path=path, timeout=.1,
                                       poll_interval=.02)
            watchdog.start()
            time.sleep(.14)
            watchdog.stop()
            self.assertFalse(path.exists())

    def test_native_timer_records_stalled_gui(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hangs.log'
            watchdog = GuiHangWatchdog(enabled=True, path=path, timeout=.2,
                                       poll_interval=.025)
            watchdog.start()
            try:
                # No GUI beats; native fault handler must fire without Python
                # monitor thread or the Qt event loop making progress.
                time.sleep(.45)
            finally:
                watchdog.stop()
            data = path.read_text(encoding='utf-8')
            self.assertIn('Timeout (0:00:00.200000)', data)
            self.assertIn('test_native_timer_records_stalled_gui', data)

    def test_regular_heartbeat_prevents_stack_dump(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hangs.log'
            watchdog = GuiHangWatchdog(enabled=True, path=path, timeout=.25,
                                       poll_interval=.04)
            watchdog.start()
            try:
                for _ in range(9):
                    watchdog.beat()
                    time.sleep(.035)
            finally:
                watchdog.stop()
            self.assertNotIn('Timeout', path.read_text(encoding='utf-8'))

    def test_start_stop_idempotence(self):
        with tempfile.TemporaryDirectory() as folder:
            watchdog = GuiHangWatchdog(enabled=True, path=Path(folder)/'hangs.log',
                                       timeout=.2, poll_interval=.02)
            watchdog.start()
            watchdog.start()
            watchdog.stop()
            watchdog.stop()


if __name__ == '__main__':
    unittest.main()
