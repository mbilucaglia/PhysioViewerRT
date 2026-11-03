import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from physiolab.asr.asr_tasks import calibration_references, eeg_configuration, fit_training_asr
from physiolab.calibrations.calibration import analyze_eyc, analyze_bsl
from physiolab.signals.processing import Processor
from physiolab.ui.gui import MainWindow


class ReferenceReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        fs = 128
        t = np.arange(fs * 60) / fs
        rng = np.random.default_rng(31)
        data = np.column_stack([10*np.sin(2*np.pi*(9+i)*t) for i in range(4)])
        data += rng.normal(0, 2, data.shape)
        cls.eeg = dict(data=data, fs=fs, channels=['F3','F4','O1','O2'],
                       timestamps=t, units=['uV']*4)
        cls.model = fit_training_asr(cls.eeg)

    def test_asr_replays_both_references_and_preserves_peripheral_statistics(self):
        peripheral = {'SCL': {'mu': 3.}}
        result = calibration_references(self.eeg, self.eeg,
            {'metrics': {'EDA': peripheral}}, 8., self.model, eeg_configuration(self.eeg))
        self.assertEqual(result['eyc']['eeg_asr_model_id'], self.model.model_id)
        self.assertEqual(result['bsl']['source_configurations']['EEG']['asr_model_id'], self.model.model_id)
        self.assertEqual(result['bsl']['iaf_hz_used'], result['eyc']['iaf_hz'])
        self.assertEqual(result['bsl']['metrics']['EDA'], peripheral)

    def test_filters_replayed_without_mutating_recordings(self):
        live = eeg_configuration(self.eeg)
        live['preprocessing'] = {'preset':'off', 'notch':False}
        result = calibration_references(self.eeg, self.eeg, {}, 8., None, live)
        expected = analyze_eyc({**self.eeg, 'preprocessing':live['preprocessing']})
        self.assertEqual(result['eyc'], expected)
        self.assertEqual(result['bsl']['source_configurations']['EEG']['preprocessing'], live['preprocessing'])
        self.assertNotIn('preprocessing', self.eeg)

    def test_changed_channels_or_conversion_rejected(self):
        for key, value in [('channels',['O1','O2']), ('conversion',{'gain':2})]:
            live = eeg_configuration(self.eeg)
            live[key] = value
            with self.assertRaisesRegex(ValueError, key):
                calibration_references(self.eeg, self.eeg, {}, 10., None, live)

    def test_metrics_start_without_asr_and_stay_open_during_reference_replay(self):
        eye = analyze_eyc(self.eeg)
        baseline = analyze_bsl({'EEG': self.eeg}, eye['iaf_hz'])
        with patch.object(MainWindow, 'refresh', lambda self: None):
            window = MainWindow()
        try:
            window.apply_calibration('EYC', {'analysis': eye}, streams={'EEG': self.eeg})
            window.apply_calibration('BSL', {'analysis': baseline}, streams={'EEG': self.eeg})
            self.assertFalse(window.asr_session.enabled)
            self.assertIsNone(window.asr_session.model)
            self.assertTrue(window.eeg_reference_pending)
            self.assertTrue(window.update_metrics_availability())
            window.tabs.setCurrentWidget(window.metrics_page)
            window.update_metrics_availability()
            self.assertIs(window.tabs.currentWidget(), window.metrics_page)
            # Pending references cannot be used to normalize EEG prematurely.
            self.assertNotIn('EEG', window.metric_references())
            deadline = time.monotonic()+15
            while window.eeg_reference_pending and time.monotonic()<deadline:
                self.app.processEvents()
                time.sleep(.005)
            self.assertFalse(window.eeg_reference_pending)
            self.assertIsNone(window.eeg_reference_error)
            self.assertTrue(window.update_metrics_availability())
            self.assertIn('EEG', window.metric_references())
            processor = Processor('EEG', self.eeg['fs'], 4, self.eeg['channels'],
                                  iaf_hz=window.iaf_hz)
            for start in range(0, 3*self.eeg['fs'], self.eeg['fs']//2):
                samples = self.eeg['data'][start:start+self.eeg['fs']//2]
                stamps = self.eeg['timestamps'][start:start+len(samples)]
                metric = processor.push(samples)
                window.receive('EEG', samples, processor.last_filtered_chunk,
                               self.eeg['channels'], metric, self.eeg['fs'], stamps)
            for name in ('AWI', 'BAR'):
                self.assertGreater(len(window.metric_state.history['EEG', name]), 1)
                value = window.metric_state.latest['EEG'][name]
                self.assertIsNotNone(window.displayed_value('EEG', name, value))
            for page in (window.metrics_page, window.affect_page):
                self.assertTrue(window.tabs.isTabEnabled(window.tabs.indexOf(page)))
        finally:
            window.close()
            self.app.processEvents()

    def test_eeg_reference_error_does_not_lock_peripheral_metrics(self):
        with patch.object(MainWindow, 'refresh', lambda self: None):
            window = MainWindow()
        try:
            reference = {'mu': 60., 'sigma': 5.}
            window.apply_calibration('EYC', {'analysis': {'iaf_hz': 10.}})
            window.apply_calibration('BSL', {'analysis': {'metrics': {
                'PPG': {'HR': reference}, 'EEG': {'AWI': reference}}}})
            window.tabs.setCurrentWidget(window.metrics_page)
            window.calibration_references_ready(window.asr_session.reference_generation,
                                                None, 'EEG calibration channels differ')
            self.assertTrue(window.update_metrics_availability())
            self.assertIs(window.tabs.currentWidget(), window.metrics_page)
            self.assertNotIn('EEG', window.metric_references())
            self.assertEqual(window.metric_references()['PPG']['HR'], reference)
            self.assertIn('channels differ', window.metric_status['EEG'].text())
            window.clear_calibration('BSL')
            self.assertFalse(window.update_metrics_availability())
        finally:
            window.close()
            self.app.processEvents()

    def test_gui_retains_samples_and_ignores_superseded_results(self):
        with patch.object(MainWindow, 'refresh', lambda self:None):
            window = MainWindow()
        try:
            window.apply_calibration('EYC', {'analysis':{'iaf_hz':8.}}, streams={'EEG':self.eeg})
            self.assertIsNot(window.eyc_recording['data'], self.eeg['data'])
            self.assertTrue(window.eeg_reference_pending)
            generation = window.asr_session.reference_generation
            window.clear_calibration('EYC')
            window.calibration_references_ready(generation, {'iaf_hz':12., 'eyc':{}, 'bsl':None}, None)
            self.assertIsNone(window.loaded_eyc)
            self.assertIsNone(window.eyc_recording)
            self.assertEqual(window.iaf_hz, 10.)
            window.apply_calibration('EYC', {'analysis':{'iaf_hz':8.}}, streams={'EEG':self.eeg})
            deadline = time.monotonic()+15
            while window.eeg_reference_pending and time.monotonic()<deadline:
                self.app.processEvents()
                time.sleep(.005)
            self.assertFalse(window.eeg_reference_pending)
            self.assertIsNone(window.eeg_reference_error)
            self.assertAlmostEqual(window.iaf_hz, analyze_eyc(self.eeg)['iaf_hz'])
            window.calibration_references_ready(window.asr_session.reference_generation, None, 'incompatible')
            self.assertFalse(window.update_metrics_availability())
            self.assertNotIn('EEG', window.metric_references())
        finally:
            window.close()
            self.app.processEvents()
