"""Hang watchdog regression tests without Qt or a real LSL source."""
import tempfile
import time
import unittest
from pathlib import Path

from physiolab.hang_watchdog import GuiHangWatchdog


class GuiWatchdogTests(unittest.TestCase):
    def test_disabled_watchdog_never_creates_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hangs.log'
            watchdog = GuiHangWatchdog(enabled=False, path=path, timeout=.1,
                                       poll_interval=.02)
            watchdog.start()
            time.sleep(.14)
            watchdog.stop()
            self.assertFalse(path.exists())

    def test_stall_writes_thread_stacks_without_gui_thread(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hangs.log'
            watchdog = GuiHangWatchdog(enabled=True, path=path, timeout=.12,
                                       poll_interval=.025)
            watchdog.start()
            try:
                deadline = time.monotonic() + 2.0
                while not path.exists() and time.monotonic() < deadline:
                    time.sleep(.025)
            finally:
                watchdog.stop()
            self.assertTrue(path.exists())
            text = path.read_text(encoding='utf-8')
            self.assertIn('GUI HEARTBEAT STALLED', text)
            self.assertIn('GuiWatchdogTests', text)

    def test_heartbeat_prevents_short_false_alarm(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hangs.log'
            watchdog = GuiHangWatchdog(enabled=True, path=path, timeout=.2,
                                       poll_interval=.02)
            watchdog.start()
            try:
                for _ in range(5):
                    watchdog.beat()
                    time.sleep(.025)
            finally:
                watchdog.stop()
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
