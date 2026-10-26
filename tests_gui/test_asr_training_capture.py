"""Subject-facing quality state and automatic accepted-data progress."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtWidgets import QApplication
from physiolab.asr_training_dialog import ASRTrainingDialog

class ASRTrainingDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_subject_instructions_and_progress_use_accepted_not_elapsed_seconds(self):
        dialog = ASRTrainingDialog(60.)
        try:
            dialog.show_status({'state':'movement','reason':'Possible movement—relax and keep still.',
                'accepted_seconds':20., 'rejected_seconds':10.}, 32.)
            self.assertIn('keep still', dialog.quality.text())
            self.assertIn('20 / 60', dialog.count.text())
            self.assertEqual(dialog.bar.value(), 33)
            dialog.show_status({'state':'good','reason':'Signal looks stable—keep still.',
                'accepted_seconds':60., 'rejected_seconds':10.}, 72., fitting=True)
            self.assertIn('Checking ASR fit', dialog.fit_status.text())
            self.assertEqual(dialog.bar.value(), 100)
            self.assertTrue(dialog.isModal())
        finally:
            dialog.close()


class AdaptiveTrainingLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from physiolab.gui import MainWindow
        from physiolab.source_conversion import SourceConversion
        from physiolab.metric_observation import source_configuration
        with patch.object(MainWindow, 'refresh', lambda self:None):
            window = MainWindow()
        window.timer.stop()
        names = ['F3','F4','O1','O2']
        conversion = SourceConversion()
        config = source_configuration('EEG',128.,names,{},conversion.metadata(),['uV']*4)
        worker = SimpleNamespace(active=True, source_configuration=config,
            info=SimpleNamespace(nominal_srate=lambda:128.), selected_names=names,
            preprocessing=config['preprocessing'], conversion=conversion,
            source_units=['uV']*4, output_units=['uV']*4, latest_source_timestamp=None,
            asr_training_monitor=None)
        window.workers['EEG'] = worker
        return window, worker

    def test_cancel_keeps_previous_model_and_releases_monitor(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        window, worker = self.make_window()
        old = SimpleNamespace(settings=SimpleNamespace(cutoff=20.))
        window.asr_session.model = old
        try:
            with patch.object(ASRTrainingDialog, 'exec', return_value=ASRTrainingDialog.DialogCode.Rejected):
                window.train_eeg_asr()
            self.assertIs(window.asr_session.model, old)
            self.assertIsNone(worker.asr_training_monitor)
            self.assertIsNone(window.capture)
        finally:
            window.workers.clear()
            window.close()
            self.app.processEvents()

    def test_failed_fit_accumulates_more_accepted_data_then_completes_automatically(self):
        from unittest.mock import patch
        from PySide6.QtCore import QTimer
        import numpy as np
        from physiolab.processing import Processor
        from physiolab.asr_tasks import fit_training_asr
        window, worker = self.make_window()
        rng = np.random.default_rng(2026)
        times = np.arange(160*128)/128.
        data = np.column_stack([10*np.sin(2*np.pi*(9+i*.5)*times+i) for i in range(4)])
        data += rng.normal(0,2,data.shape)
        proc = Processor('EEG',128.,4,worker.selected_names,preprocessing=worker.preprocessing)
        proc.push(data)
        filtered = proc.last_preprocessed_chunk
        attempts = []
        original_exec = ASRTrainingDialog.exec
        def fit(eeg, settings):
            attempts.append(len(eeg['data'])/128.)
            if len(attempts) == 1:
                raise ValueError('Test: more clean data required')
            return fit_training_asr(eeg, settings)
        def run(dialog):
            timer = QTimer(dialog)
            cursor = [0]
            def feed():
                i = cursor[0]
                if i < 160:
                    worker.asr_training_monitor.push(data[i*128:(i+1)*128],
                        filtered[i*128:(i+1)*128], times[i*128:(i+1)*128])
                    cursor[0] += 1
            timer.timeout.connect(feed)
            timer.start(10)
            QTimer.singleShot(15000, dialog.reject)
            try:
                return original_exec(dialog)
            finally:
                timer.stop()
        try:
            with patch.object(ASRTrainingDialog,'exec',run), \
                 patch('physiolab.asr_tasks.fit_training_asr',side_effect=fit), \
                 patch.object(window,'set_eeg_asr_enabled') as enabled, \
                 patch.object(window,'show_asr_training_report'):
                window.train_eeg_asr()
            self.assertGreaterEqual(len(attempts), 2)
            self.assertGreaterEqual(attempts[0], 60.)
            self.assertGreaterEqual(attempts[1]-attempts[0], 10.)
            self.assertIsNotNone(window.asr_session.model)
            self.assertGreaterEqual(window.asr_session.model.baseline_seconds, 70.)
            self.assertIsNone(worker.asr_training_monitor)
            enabled.assert_called_with(True)
        finally:
            window.workers.clear()
            window.close()
            self.app.processEvents()
