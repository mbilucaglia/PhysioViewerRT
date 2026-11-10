"""File operations remain isolated, responsive, and owned during shutdown."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from physiolab.gui import MainWindow
from physiolab.calibration_tasks import CalibrationIOTask
from physiolab.calibration import save_calibration, load_calibration
from physiolab.task_lifecycle import OperationCancelled
from physiolab.eeg_bands import IAF_BAND_CONVENTION, derive_iaf_bands


class CalibrationIOTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch.object(MainWindow, 'refresh'):
            self.window = MainWindow()
        self.window.timer.stop()
        self.streams = {'EEG': {'data': np.ones((8, 1)), 'timestamps': np.arange(8.),
                               'fs': 128., 'channels': ['O1']}}

    def tearDown(self):
        self.window.close()
        deadline = time.monotonic() + 3
        while not self.window._closed and time.monotonic() < deadline:
            self.app.processEvents()
            threading.Event().wait(.001)
        self.assertTrue(self.window._closed)

    def test_task_owns_save_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'snapshot.npz'
            analysis = {'value': 1}
            task = CalibrationIOTask('save', path, 'EYC', self.streams, analysis)
            self.streams['EEG']['data'][:] = 99.
            analysis['value'] = 2
            task.run()
            meta, streams = load_calibration(path, 'EYC')
            self.assertEqual(meta['analysis'], {'value': 1})
            self.assertTrue(np.all(streams['EEG']['data'] == 1.))
            task.deleteLater()

    def test_slow_save_runs_off_gui_and_duplicate_request_is_rejected(self):
        entered, release = threading.Event(), threading.Event()
        gui_thread = threading.get_ident()
        calls, ticks, duplicate_errors, navigation = [], [], [], []

        def slow_save(*args):
            calls.append(threading.get_ident())
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Test heartbeat did not release I/O')
            return save_calibration(*args)

        def heartbeat():
            if entered.is_set():
                ticks.append(threading.get_ident())
                if len(ticks) == 1:
                    dialog = self.window._calibration_dialog
                    self.window.tabs.setCurrentWidget(self.window.raw_page)
                    navigation.append((dialog.isModal(), self.app.activeModalWidget(),
                                       self.window.tabs.currentWidget() is self.window.raw_page))
                    try:
                        self.window._run_calibration_io('save', path, 'EYC', self.streams, {})
                    except OperationCancelled as error:
                        duplicate_errors.append(str(error))
                if len(ticks) >= 3:
                    release.set()

        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(heartbeat)
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'slow.npz'
                timer.start()
                with patch('physiolab.calibration_tasks.save_calibration', side_effect=slow_save):
                    self.window._run_calibration_io('save', path, 'EYC', self.streams, {})
                self.assertEqual(len(calls), 1)
                self.assertNotEqual(calls[0], gui_thread)
                self.assertGreaterEqual(len(ticks), 3)
                self.assertEqual(set(ticks), {gui_thread})
                self.assertEqual(len(duplicate_errors), 1)
                self.assertEqual(navigation, [(False, None, True)])
                self.assertTrue(path.exists())
        finally:
            release.set()
            timer.stop()

    def test_close_during_save_waits_for_commit_and_preserves_task(self):
        entered, release = threading.Event(), threading.Event()

        def slow_save(*args):
            entered.set()
            release.wait(3)
            return save_calibration(*args)

        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: self.window.close() if entered.is_set() else None)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'closing.npz'
            try:
                timer.start()
                with patch('physiolab.calibration_tasks.save_calibration', side_effect=slow_save):
                    with self.assertRaises(OperationCancelled):
                        self.window._run_calibration_io('save', path, 'EYC', self.streams, {})
                    self.assertFalse(self.window._closed)
                    release.set()
                    deadline = time.monotonic() + 3
                    while not self.window._closed and time.monotonic() < deadline:
                        self.app.processEvents()
                        threading.Event().wait(.001)
                    self.assertTrue(self.window._closed)
                self.assertEqual(load_calibration(path, 'EYC')[0]['type'], 'EYC')
            finally:
                release.set()
                timer.stop()

    def test_invalid_load_leaves_active_calibration_unchanged(self):
        self.window.apply_calibration('EYC', {'analysis': {'iaf_hz': 10.}})
        previous = self.window.loaded_eyc
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'invalid.npz'
            path.write_bytes(b'invalid archive')
            with patch('physiolab.gui.QFileDialog.getOpenFileName', return_value=(str(path), '')), \
                    patch.object(QMessageBox, 'critical') as error, \
                    self.assertLogs('physiolab.calibration_tasks', level='ERROR') as logs:
                self.window.load_existing('EYC')
            self.assertEqual(len(logs.records), 1)
            self.assertIsNotNone(logs.records[0].exc_info)
            error.assert_called_once()
            self.assertIs(self.window.loaded_eyc, previous)
            self.assertEqual(self.window.iaf_hz, 10.)

    def test_eyc_bands_survive_background_analysis_storage_and_coordinator_replay(self):
        times = np.arange(60 * 128) / 128.
        streams = {'EEG': {'data': np.sin(2*np.pi*10*times)[:, None],
                          'timestamps': times, 'fs': 128., 'channels': ['O1']}}
        analysis = self.window.analyze_calibration_background('EYC', streams)
        expected = derive_iaf_bands(analysis['iaf_hz'])
        self.assertEqual(analysis['iaf_bands_hz'], expected)
        self.assertEqual(analysis['iaf_band_convention'], IAF_BAND_CONVENTION)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bands.npz'
            self.window._run_calibration_io('save', path, 'EYC', streams, analysis)
            loaded = self.window._run_calibration_io('load', path, 'EYC')
            with patch.object(self.window, '_apply_asr_metric_references'):
                self.window.apply_calibration('EYC', loaded.metadata, str(path), loaded.streams)
            # Exercise the real replay path after committing the loaded state.
            self.window._apply_asr_metric_references()
            deadline = time.monotonic() + 5
            while self.window.eeg_reference_tasks and time.monotonic() < deadline:
                self.app.processEvents()
                threading.Event().wait(.001)
            self.assertFalse(self.window.eeg_reference_tasks)
            self.assertIsNone(self.window.eeg_reference_error)
            self.assertEqual(self.window.loaded_eyc['analysis']['iaf_bands_hz'], expected)
            self.window.show()
            self.window.tabs.setCurrentWidget(self.window.raw_page)
            self.window.set_raw_focus('TOPO', True)
            self.app.processEvents()
            with patch.object(self.window.topography, 'tick') as tick:
                self.window.render_frame()
            tick.assert_called_once()
            self.assertEqual(tick.call_args.args[2], expected)
