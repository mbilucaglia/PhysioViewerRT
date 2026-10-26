import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QLabel
from physiolab.gui import MainWindow


class TrainingReportGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch.object(MainWindow, 'refresh', lambda self:None):
            self.window = MainWindow()
        self.model = SimpleNamespace(baseline_seconds=45., clean_seconds=36.,
            settings=SimpleNamespace(minimum_baseline_seconds=30., cutoff=20.),
            channels=('F3','F4'), fs=128.)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_report_is_nonmodal_and_refreshes_when_reopened(self):
        self.window.asr_session.model = self.model
        self.window.update_asr_availability()
        self.assertTrue(self.window.asr_view.report.isEnabled())
        self.window.show_asr_training_report()
        dialog = self.window._asr_report_dialog
        self.assertFalse(dialog.isModal())
        self.assertEqual(dialog.findChild(QLabel, 'retainedValue').text(), '36.0 s (80.0%)')
        dialog.close()
        self.model.settings.cutoff = 25.
        self.window.show_asr_training_report()
        self.assertIs(self.window._asr_report_dialog, dialog)
        self.assertEqual(dialog.findChild(QLabel, 'thresholdValue').text(), '25 σ')

    def test_only_new_successful_training_opens_report_automatically(self):
        window = self.window
        window.asr_session.generation = 2
        with patch.object(window, 'show_asr_training_report') as show, patch.object(window, 'update_asr_availability'):
            window.asr_session.busy = True
            window.eeg_asr_fitted(1, self.model, None)
            self.assertTrue(window.asr_session.busy)
            show.assert_not_called()
            window.eeg_asr_fitted(2, None, 'fit failed')
            show.assert_not_called()
            window.eeg_asr_fitted(2, self.model, None)
            show.assert_called_once()
            window.eeg_asr_fitted(2, self.model, None)
            show.assert_called_once()
            window.asr_session.generation = 3
            window.eeg_asr_fitted(3, self.model, None)
            self.assertEqual(show.call_count, 2)
