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

    def test_ei_follows_each_views_selected_normalization_independently(self):
        from physiolab.calibration import normalize
        with patch.object(MainWindow, 'refresh', lambda self: None):
            w = MainWindow()
        try:
            ref = {'mu': 0., 'sigma': 1., 'median': 0., 'mad': 1., 'iqr': 1., 'minimum': -2., 'maximum': 2.}
            ei_ref = {'mu': .2, 'sigma': .1, 'median': .1, 'mad': .2,
                      'iqr': .3, 'minimum': -.1, 'maximum': .1}
            w.loaded_bsl = {'analysis': {'metrics': {'PPG': {'HR':ref},
                'EDA': {'SCL':ref}, 'EI': {'EI':ei_ref}},
                'tonic_sc': {'configuration_id':'test-pipeline'}}}
            w._tonic_live_configuration = 'test-pipeline'
            w.refresh_affect_references()
            w.metric_state.update('PPG', {'HR':1.},time.monotonic()-1.)
            w.metric_state.update('EDA', {'SCL':1.},time.monotonic()-1.)
            raw = emotional_index_z(1.,1.)
            with patch.object(w,'sync_affect_sources',lambda:None):
                w.affect_view.set_peripheral_available(True)
                w.affect_view.set_active(True)
                for affect_mode in ('zscore','zmad','robust_iqr','minmax'):
                    w.affect_view.normalization.setCurrentIndex(w.affect_view.normalization.findData(affect_mode))
                    for metric_mode in ('identity','zscore','zmad','robust_iqr','minmax'):
                        w.normalization.setCurrentIndex(w.normalization.findData(metric_mode))
                        w.refresh_affect_view()
                        w.refresh_metric_labels()
                        self.assertAlmostEqual(w.affect_view.ei_plot.current,normalize(raw,ei_ref,affect_mode))
                        self.assertAlmostEqual(w.displayed_value('EI','EI',raw),normalize(raw,ei_ref,metric_mode))
                self.assertGreater(w.affect_view.ei_plot.current,1., 'Minmax must not clip outside-baseline EI')
                self.assertIn('baseline minimum',w.affect_view.ei_note.text())
                self.assertIn('HRz +1.00',w.affect_view.ei_diagnostics.text())
                self.assertEqual(w.metric_state.latest['EI']['EI'],raw)
                w.normalization.setCurrentIndex(w.normalization.findData('identity'))
                for mode, field in (('zscore','sigma'),('zmad','mad'),('robust_iqr','iqr'),('minmax','maximum')):
                    broken = {**ei_ref, field: 0. if mode != 'minmax' else ei_ref['minimum']}
                    w.loaded_bsl['analysis']['metrics']['EI']['EI'] = broken
                    w.affect_view.normalization.setCurrentIndex(w.affect_view.normalization.findData(mode))
                    w.refresh_affect_view()
                    self.assertIsNone(w.affect_view.ei_plot.current)
                    self.assertIn('variability',w.affect_view.ei_status.text())
                    self.assertEqual(w.displayed_value('EI','EI',raw),raw)
                w.loaded_bsl['analysis']['metrics']['EI'] = {}
                w.refresh_affect_view()
                self.assertIsNone(w.affect_view.ei_plot.current)
                w.loaded_bsl['analysis']['metrics']['EI'] = {'EI':ei_ref}
                w._tonic_live_configuration = 'different-pipeline'
                w.refresh_affect_references()
                w.refresh_affect_view()
                self.assertIsNone(w.affect_view.ei_plot.current)
                self.assertFalse(w.metric_state.history['EI','EI'])
        finally:
            w.close()
            self.app.processEvents()

    def test_trace_selection_invalidates_old_center_and_refreshes_even_when_paused(self):
        with patch.object(MainWindow,'refresh',lambda self:None):
            w = MainWindow()
        try:
            w.raw_display.paused = True
            w.raw_display.references['EEG'] = ([100.], [1.])
            before = w.raw_display.epoch
            w.show_processed.setChecked(False)
            self.assertNotIn('EEG', w.raw_display.references)
            self.assertGreater(w.raw_display.epoch, before)
            self.assertTrue(w._raw_trace_selection_refresh)
            w.show_raw.setChecked(False)
            w.show_processed.setChecked(True)
            self.assertTrue(w._raw_trace_selection_refresh)
        finally:
            w.close()
            self.app.processEvents()

    def test_selected_trace_centers_redraw_while_paused_in_both_renderers(self):
        import numpy as np
        from pylsl import local_clock
        with patch.object(MainWindow,'refresh',lambda self:None):
            w = MainWindow()
        def pump(predicate):
            deadline = time.monotonic()+4.
            while time.monotonic() < deadline:
                self.app.processEvents()
                if predicate():
                    return True
                time.sleep(.005)
            return False
        try:
            w.show()
            w.tabs.setCurrentWidget(w.raw_page)
            times = np.arange(1280)/256.
            wave = np.column_stack((np.sin(2*np.pi*4*times),np.sin(2*np.pi*6*times)))
            w.receive('EEG',100.+wave,3.+wave*.5,['Fp1','Fp2'],None,256.,local_clock()-5.+times)
            self.assertTrue(pump(lambda: 'EEG' in w.raw_display.frames))
            modes = (0,1) if os.environ.get('QT_QPA_PLATFORM') == 'windows' else (0,)
            for renderer in modes:
                w.raw_renderer_choice.setCurrentIndex(renderer)
                w.raw_display.paused = True
                for raw_visible, clean_visible, expected in ((True,False,100.),(False,True,3.),(True,True,3.)):
                    w.show_raw.setChecked(raw_visible)
                    w.show_processed.setChecked(clean_visible)
                    w.raw_trace_selection_changed()
                    self.assertTrue(pump(lambda: 'EEG' in w.raw_display.frames
                        and not w._raw_trace_selection_refresh), f'Paused selection did not redraw: renderer={renderer}, raw={raw_visible}, clean={clean_visible}, bounds={w.raw_display.bounds}, x={w.plots["EEG"].viewRange()[0]}')
                    centers = w.raw_display.frames['EEG'][3]
                    np.testing.assert_allclose(centers,expected,atol=1.)
                    frame = w.raw_display.frames['EEG']
                    active = frame[2] if clean_visible else frame[1]
                    np.testing.assert_allclose(np.median(active,axis=0),np.arange(len(centers))*6.,atol=1e-8)
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
            self.assertIn('ASR monitoring', w.raw_asr_status.accessibleName())
            worker.asr_last_correction_at = 10.
            w.refresh_asr_indicator(10.)
            self.assertIn('ASR correcting', w.raw_asr_status.accessibleName())
            worker.asr_status = 'ASR bypassed after processing error: failure'
            w.refresh_asr_indicator(10.)
            self.assertIn('BYPASSED', w.raw_asr_status.accessibleName())
            self.assertIn('failure', w.raw_asr_status.toolTip())
        finally:
            w.workers.clear()
            w.close()
            self.app.processEvents()
