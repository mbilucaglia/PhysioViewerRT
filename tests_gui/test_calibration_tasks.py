"""Modal calibration analysis keeps Qt timers moving and reports results."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from physiolab.gui import MainWindow
from physiolab.metric_observation import source_configuration


class CalibrationTaskTests(unittest.TestCase):
    def test_completed_bsl_is_active_without_retraining_asr_even_when_not_saved(self):
        app = QApplication.instance() or QApplication([])
        with patch.object(MainWindow, 'refresh', lambda self: None):
            window = MainWindow()
        eeg = {'data': np.zeros((60*128, 2)), 'fs':128., 'channels':['F3','F4'],
               'timestamps':np.arange(60*128)/128., 'units':['uV']*2}
        worker = SimpleNamespace(isRunning=lambda:True, active=True,
            info=SimpleNamespace(nominal_srate=lambda:128.), selected_names=eeg['channels'],
            preprocessing={}, conversion=SimpleNamespace(metadata=lambda:{}),
            source_units=['uV']*2, output_units=['uV']*2, latest_source_timestamp=0.)
        window.workers['EEG'] = worker
        analysis = {'metrics':{'EEG':{'AWI':{'mu':0.,'sigma':1.}}}, 'iaf_hz_used':10.}
        try:
            with patch('physiolab.gui.CalibrationScreen') as screen, \
                    patch('physiolab.gui.CalibrationSession') as session, \
                    patch.object(QMessageBox,'information'), \
                    patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No), \
                    patch.object(window,'analyze_calibration_background',return_value=analysis), \
                    patch.object(window,'inspect_calibration'), \
                    patch.object(window,'fit_eeg_asr') as fit:
                screen.return_value.exec.return_value = QDialog.DialogCode.Accepted
                session.return_value.finish.return_value = {'EEG':eeg}
                window.record_calibration('BSL')
                fit.assert_not_called()
                self.assertEqual(window.loaded_bsl['analysis'], analysis)
                self.assertEqual(window.calibration_file_labels['BSL'].text(), 'Loaded (unsaved)')
        finally:
            window.workers.clear()
            window.close()
            app.processEvents()

    def test_incompatible_source_configuration_suppresses_only_its_response(self):
        app = QApplication.instance() or QApplication([])
        with patch.object(MainWindow, 'refresh', lambda self: None):
            window = MainWindow()
        reference = {'mu': 0., 'sigma': 1.}
        configs = {kind: source_configuration(kind, fs, names, {}, {}, [unit]*len(names))
                   for kind, fs, names, unit in (
                       ('EEG', 256., ['F3','F4'], 'uV'), ('PPG',128.,['PPG'],'a.u.'),
                       ('EDA',32.,['SC'],'uS'))}
        try:
            window._tonic_live_configuration = 'test-pipeline'
            window.apply_calibration('BSL', {'analysis': {'tonic_sc': {
                'configuration_id': 'test-pipeline'}, 'source_configurations': configs,
                'metrics': {'EEG': {'AWI': reference, 'BAR': reference},
                            'PPG': {'HR': reference}, 'EDA': {'SCL': reference}}}})
            for kind, config in configs.items():
                window.workers[kind] = SimpleNamespace(source_configuration=dict(config))
            window.refresh_affect_references()
            window.affect_state.update('EEG', {'AWI': 1., 'BAR': 1.}, 100.)
            window.affect_state.update('PPG', {'HR': 1.}, 100.)
            window.affect_state.update('EDA', {'SCL': 1.}, 100.)
            self.assertTrue(all(r.current is not None
                                for r in window.affect_state.snapshot(100.,60.).responses))
            window.workers['EEG'].source_configuration['channels'] = ['F3']
            window.refresh_affect_references()
            responses = window.affect_state.snapshot(100.,60.).responses
            self.assertIsNone(responses[0].current)
            self.assertIsNotNone(responses[1].current)
            window.workers['EEG'].source_configuration = dict(configs['EEG'])
            window.workers['PPG'].source_configuration['preprocessing'] = {'preset':'off','notch':True}
            window.refresh_affect_references()
            responses = window.affect_state.snapshot(100.,60.).responses
            self.assertIsNotNone(responses[0].current)
            self.assertIsNone(responses[1].current)
        finally:
            window.workers.clear()
            window.close()
            app.processEvents()

    def test_new_iaf_requires_matching_eeg_baseline_for_affect(self):
        app = QApplication.instance() or QApplication([])
        with patch.object(MainWindow, 'refresh', lambda self: None):
            window = MainWindow()
        reference = {'mu': 0., 'sigma': 1.}
        try:
            window.apply_calibration('EYC', {'analysis': {'iaf_hz': 10.}})
            window.apply_calibration('BSL', {'analysis': {'iaf_hz_used': 10.,
                'metrics': {'EEG': {'AWI': reference, 'BAR': reference}}}})
            window.affect_state.update('EEG', {'AWI': .2, 'BAR': .5}, 100.)
            self.assertIsNotNone(window.affect_state.snapshot(100., 60.).responses[0].current)
            window.apply_calibration('EYC', {'analysis': {'iaf_hz': 11.}})
            window.affect_state.update('EEG', {'AWI': .2, 'BAR': .5}, 101.)
            self.assertIsNone(window.affect_state.snapshot(101., 60.).responses[0].current)
        finally:
            window.close()
            app.processEvents()

    def test_background_baseline_analysis_delivers_tonic_refs_without_blocking_events(self):
        app = QApplication.instance() or QApplication([])
        with patch.object(MainWindow, 'refresh', lambda self: None):
            window = MainWindow()
        ticks = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start()
        fs = 32.
        timestamps = np.arange(int(60*fs))/fs
        try:
            result = window.analyze_calibration_background('BSL', {'EDA': {
                'data': (4.+.05*np.sin(timestamps))[:, None], 'timestamps': timestamps,
                'fs': fs, 'channels': ['SC'], 'units': ['uS']}})
            self.assertTrue(ticks)
            self.assertIn('SCL', result['metrics']['EDA'])
            if result.get('tonic_sc'):
                self.assertIn('SCL', result['metrics']['EDA'])
        finally:
            timer.stop()
            window.close()
            app.processEvents()
