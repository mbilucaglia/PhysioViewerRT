"""One normalization boundary for EI in both views and consistent metric units."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from physiolab.gui import MainWindow
from physiolab.emotion import emotional_index_z

class LiveFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ei_baseline_scale_matches_metrics_and_affect_for_every_selector(self):
        with patch.object(MainWindow, 'refresh', lambda self: None):
            w = MainWindow()
        try:
            ref = {'mu': 0., 'sigma': 1., 'median': 0., 'mad': 1., 'iqr': 1., 'minimum': -2., 'maximum': 2.}
            w.loaded_bsl = {'analysis': {'metrics': {
                'PPG': {'HR': ref}, 'EDA': {'SCL': ref},
                'EI': {'EI': {'mu': .2, 'sigma': .1}}},
                'tonic_sc': {'configuration_id': 'test-pipeline'}}}
            w._tonic_live_configuration = 'test-pipeline'
            w.refresh_affect_references()
            w.metric_state.update('PPG', {'HR': 1.}, time.monotonic())
            w.metric_state.update('EDA', {'SCL': 1.}, time.monotonic())
            expected = (emotional_index_z(1., 1.)-.2)/.1
            with patch.object(w, 'sync_affect_sources', lambda: None):
                w.affect_view.set_peripheral_available(True)
                w.affect_view.set_active(True)
                for mode in ('identity', 'zscore', 'zmad', 'robust_iqr', 'minmax'):
                    w.normalization.setCurrentIndex(w.normalization.findData(mode))
                    w.refresh_affect_view()
                    w.refresh_metric_labels()
                    self.assertAlmostEqual(w.affect_view.ei_plot.current, expected)
                    self.assertIn('σ', w.metric_labels['EI', 'EI'].text())
                    self.assertAlmostEqual(w.displayed_value('EI', 'EI', emotional_index_z(1.,1.)), expected)
                self.assertIn('HRz +1.00', w.affect_view.ei_diagnostics.text())
                w._tonic_live_configuration = 'different-pipeline'
                w.refresh_affect_references()
                w.refresh_affect_view()
                self.assertIsNone(w.affect_view.ei_plot.current)
                self.assertFalse(w.metric_state.history['EI', 'EI'])
        finally:
            w.close()
            self.app.processEvents()

    def test_raw_indicator_uses_worker_state_and_survives_pause(self):
        with patch.object(MainWindow, 'refresh', lambda self: None):
            w = MainWindow()
        try:
            worker = SimpleNamespace(active=True, asr_status='ASR active',
                eeg_asr_model=SimpleNamespace(model_id='test'), asr_last_processed_at=10.)
            w.workers['EEG'] = worker
            w.raw_display.paused = True
            w.refresh_asr_indicator(10.)
            self.assertIn('ASR ON', w.raw_asr_status.text())
            worker.asr_status = 'ASR bypassed after processing error: failure'
            w.refresh_asr_indicator(10.)
            self.assertIn('BYPASSED', w.raw_asr_status.text())
            self.assertIn('failure', w.raw_asr_status.toolTip())
        finally:
            w.workers.clear()
            w.close()
            self.app.processEvents()
