"""Deterministic slow-task probes for GUI lifetime and bounded scheduling."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np

from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import QApplication
from physiolab.gui import MainWindow
from physiolab.task_lifecycle import OperationCancelled
from physiolab.worker import Receiver


class HeldTask(QThread):
    completed = Signal(object, object)

    def __init__(self, entered, release, parent=None):
        super().__init__(parent)
        self.entered, self.release = entered, release

    def run(self):
        self.entered.set()
        self.release.wait(5)
        self.completed.emit({'done': True}, None)


class ArchitecturalLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def window(self):
        with patch.object(MainWindow, 'refresh'):
            window = MainWindow()
        window.timer.stop()
        return window

    def pump(self, condition, timeout=3):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            threading.Event().wait(.001)
        self.assertTrue(condition())

    def test_close_keeps_event_loop_and_task_owner_alive(self):
        window = self.window()
        entered, release = threading.Event(), threading.Event()
        task = HeldTask(entered, release, window)
        window.task_lifecycle.track(task)
        task.start()
        self.assertTrue(entered.wait(1))
        ticks = []
        timer = QTimer()
        timer.setInterval(1)
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start()
        try:
            start = time.monotonic()
            window.close()
            window.close()
            self.assertLess(time.monotonic() - start, .2)
            self.pump(lambda: len(ticks) > 2)
            self.assertFalse(window._closed)
            self.assertIn(task, window.task_lifecycle.tasks)
        finally:
            release.set()
            self.pump(lambda: window._closed)
            timer.stop()
        self.assertTrue(window.task_lifecycle.idle)

    def test_modal_analysis_close_unwinds_without_joining(self):
        window = self.window()
        entered, release = threading.Event(), threading.Event()
        task = HeldTask(entered, release, window)
        timer = QTimer()
        timer.setInterval(1)
        timer.timeout.connect(lambda: window.close() if entered.is_set() else None)
        timer.start()
        try:
            with self.assertRaises(OperationCancelled):
                window._run_calibration_task(task, 'Testing slow analysis')
            self.assertFalse(window._closed)
        finally:
            timer.stop()
            release.set()
            self.pump(lambda: window._closed)

    def test_discovery_coalesces_burst_and_closes_without_pending_restart(self):
        window = self.window()
        entered, release = threading.Event(), threading.Event()
        calls = []

        def discover():
            calls.append(True)
            entered.set()
            release.wait(5)
            return []

        try:
            with patch('physiolab.lsl_tasks.discover', side_effect=discover):
                window.refresh()
                self.assertTrue(entered.wait(1))
                for _ in range(20):
                    window.refresh()
                self.assertEqual(len(window.lsl_tasks), 1)
                release.set()
                self.pump(lambda: not window.lsl_tasks)
                self.assertEqual(len(calls), 2)
        finally:
            release.set()
            window.close()
            self.pump(lambda: window._closed)

    def test_topography_close_waits_asynchronously_for_active_future(self):
        window = self.window()
        entered, release = threading.Event(), threading.Event()

        def calculate():
            entered.set()
            release.wait(5)

        window.topography._future = window.topography._pool.submit(calculate)
        self.assertTrue(entered.wait(1))
        try:
            start = time.monotonic()
            window.close()
            self.assertLess(time.monotonic() - start, .2)
            self.assertFalse(window._closed)
        finally:
            release.set()
            self.pump(lambda: window._closed)

    def test_replay_burst_runs_first_and_latest_only(self):
        window = self.window()
        entered, release = threading.Event(), threading.Event()
        calls = []
        streams = {'EEG': {'data': np.ones((3, 1)), 'timestamps': np.arange(3.),
                           'fs': 128., 'channels': ['O1']}}
        window.calibrations.apply('EYC', {'analysis': {'iaf_hz': 10.}}, streams=streams)

        def replay(eyc, bsl, analysis, iaf, model, live):
            calls.append(iaf)
            entered.set()
            release.wait(5)
            return {'eyc': {'iaf_hz': iaf}, 'bsl': None, 'iaf_hz': iaf}

        try:
            with patch('physiolab.asr_tasks.calibration_references', side_effect=replay):
                window._apply_asr_metric_references()
                self.assertTrue(entered.wait(1))
                for iaf in (11., 12.):
                    window.iaf_hz = iaf
                    window._apply_asr_metric_references()
                self.assertEqual(len(window.eeg_reference_tasks), 1)
                release.set()
                self.pump(lambda: not window.eeg_reference_tasks and not window.eeg_reference_pending)
                self.assertEqual(calls, [10., 12.])
                self.assertEqual(window.loaded_eyc['analysis']['iaf_hz'], 12.)
        finally:
            release.set()
            window.close()
            self.pump(lambda: window._closed)

    def test_receiver_metadata_stop_retains_ownership_until_inlet_cleanup(self):
        window = self.window()
        entered, release, cleaned = threading.Event(), threading.Event(), threading.Event()
        info = SimpleNamespace(channel_count=lambda: 1, nominal_srate=lambda: 128.)

        def metadata(timeout):
            entered.set()
            release.wait(5)
            return object()

        inlet = SimpleNamespace(info=metadata, close_stream=cleaned.set)
        worker = Receiver(info, 'PPG', [0], ['P'])
        window.workers['PPG'] = worker
        window.task_lifecycle.track(worker)
        try:
            with patch('physiolab.worker.StreamInlet', return_value=inlet), \
                    patch('physiolab.worker.stream_channel_units', return_value=['a.u.']):
                worker.start()
                self.assertTrue(entered.wait(1))
                start = time.monotonic()
                window.close()
                self.assertLess(time.monotonic() - start, .2)
                self.assertFalse(window._closed)
                self.assertFalse(worker.status_snapshot().active)
                release.set()
                self.pump(lambda: window._closed)
                self.assertTrue(cleaned.is_set())
        finally:
            release.set()
            worker.request_stop()
            window.close()
            self.pump(lambda: window._closed)

    def test_receiver_control_snapshot_is_coherent_and_commands_are_nonblocking(self):
        info = SimpleNamespace(channel_count=lambda: 1, nominal_srate=lambda: 128.)
        worker = Receiver(info, 'EEG', [0], ['O1'])
        before = worker.status_snapshot()
        worker.source_configuration = {'channels': ['O1'], 'asr_model_id': 'new'}
        worker.asr_status = 'ASR active'
        worker._publish_status()
        after = worker.status_snapshot()
        self.assertIsNone(before.source_configuration)
        self.assertGreater(after.revision, before.revision)
        self.assertEqual(after.source_configuration['asr_model_id'], 'new')
        self.assertEqual(after.asr_status, 'ASR active')
        monitor = object()
        worker.iaf_hz, worker.asr_training_monitor = 11., monitor
        chunk_controls = worker._chunk_controls()
        worker.asr_training_monitor = None
        self.assertEqual(chunk_controls, (11., monitor))
        self.assertEqual(worker._chunk_controls(), (11., None))
        worker.deleteLater()

    def test_controller_draw_accepts_only_the_declared_backend_surface(self):
        class Backend:
            latest_sample_time = float('-inf')
            presentation_width = 600

            def __init__(self): self.presented = []
            def present(self, frame, view, fs):
                self.presented.append(frame)
                return True
            def reset(self): pass
            def invalidate_history(self): pass
            def history_needs_replay(self, count, duration): return True
            def close(self): pass

        window = self.window()
        backend = Backend()
        try:
            controller = window.raw_controller
            controller.backends['pyqtgraph']['PPG'] = backend
            controller.set_backend('pyqtgraph')
            controller.set_visible({'PPG'})
            controller.state.follow_live = False
            times = np.arange(20.) / 10
            data = np.sin(times)[:, None]
            controller.append('PPG', data, data, ['P'], 10., times)
            controller.state.source_bounds['PPG'] = (0., 2.)
            controller.draw()
            self.pump(lambda: any(frame is not None for frame in backend.presented))
            self.assertFalse(hasattr(backend, 'widget'))
        finally:
            window.close()
            self.pump(lambda: window._closed)
