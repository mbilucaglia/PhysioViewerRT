"""Native baseline gating, asynchronous ASR fit, and real LSL cleaning."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import threading
import unittest
import uuid
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from pylsl import StreamInfo, StreamOutlet, local_clock, resolve_byprop

from physiolab.asr_tasks import fit_training_asr
from physiolab.gui import MainWindow
from physiolab.worker import Receiver
from physiolab.calibration import analyze_bsl
from physiolab.synthetic import SyntheticPhysiology, SPECS
from physiolab.physiological_metrics import eeg_metrics


class ASRIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.fs, cls.names = 128., ['F3', 'F4', 'O1', 'O2']
        t = np.arange(int(60*cls.fs))/cls.fs
        rng = np.random.default_rng(2026)
        data = np.column_stack([10*np.sin(2*np.pi*(9+i*.5)*t+i) for i in range(4)])
        data += rng.normal(0, 2, data.shape)
        cls.eeg = {'data': data, 'fs': cls.fs, 'channels': cls.names,
                   'timestamps': t, 'units': ['uV']*4}
        cls.analysis = {'metrics': {'EEG': {'AWI': {'mu': 123., 'sigma': 2.}},
                                   'EDA': {'SCL': {'mu': 5., 'sigma': .2}}},
                        'iaf_hz_used': 10.}

    def pump(self, predicate, timeout=15):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(.005)
        return False

    def test_training_is_independent_and_baselines_follow_cleaning(self):
        with patch.object(MainWindow, 'refresh', lambda self: None):
            window = MainWindow()
        ticks = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        try:
            self.assertFalse(window.asr_view.enable.isEnabled())
            window.asr_session.set_training(self.eeg)
            timer.start()
            with patch.object(window, 'schedule_source_change') as restart:
                window.fit_eeg_asr(window.asr_view.settings(), enable_on_success=True)
                self.assertTrue(window.asr_session.busy)
                self.assertTrue(self.pump(lambda: not window.asr_session.busy))
                self.assertTrue(window.asr_session.enabled)
                self.assertIsNone(window.loaded_bsl)
                self.assertIsNone(window.loaded_eyc)
                self.assertGreater(len(ticks), 3)
                model_id = window.asr_session.model.model_id
                self.assertEqual(window.asr_session.model.channels, tuple(self.names))
                window.apply_calibration('EYC', {'analysis': {'iaf_hz': 10.}})
                window.apply_calibration('BSL', {'analysis': self.analysis}, streams={'EEG': self.eeg})
                self.assertTrue(self.pump(lambda: not window.eeg_reference_pending))
                reference = window.loaded_bsl['analysis']
                self.assertEqual(reference['source_configurations']['EEG']['asr_model_id'], model_id)
                self.assertNotEqual(reference['metrics']['EEG']['AWI']['mu'], 123.)
                self.assertEqual(reference['metrics']['EDA'], self.analysis['metrics']['EDA'])
                window.apply_calibration('EYC', {'analysis': {'iaf_hz': 11.}})
                self.assertTrue(self.pump(lambda: not window.eeg_reference_pending))
                self.assertEqual(window.loaded_bsl['analysis']['iaf_hz_used'], 11.)
                self.assertEqual(window.asr_session.model.model_id, model_id)
                window.asr_view.cutoff.setValue(25.)
                self.assertTrue(self.pump(lambda: window.asr_session.busy))
                self.assertTrue(self.pump(lambda: not window.asr_session.busy))
                self.assertTrue(self.pump(lambda: not window.eeg_reference_pending))
                self.assertEqual(window.asr_session.model.settings.cutoff, 25.)
                self.assertTrue(window.asr_session.enabled)
                window.clear_calibration('BSL')
                window.clear_calibration('EYC')
                self.assertIsNotNone(window.asr_session.model)
                self.assertTrue(window.asr_session.enabled)
        finally:
            timer.stop()
            window.close()
            self.app.processEvents()

    def test_train_button_records_fresh_live_eeg_without_baselines(self):
        stream_id = 'asr-training-'+uuid.uuid4().hex
        info = StreamInfo(stream_id, 'EEG', 4, self.fs, 'float32', stream_id)
        channels = info.desc().append_child('channels')
        for name in self.names:
            item = channels.append_child('channel')
            item.append_child_value('label', name)
            item.append_child_value('unit', 'uV')
        outlet = StreamOutlet(info)
        resolved = resolve_byprop('source_id', stream_id, minimum=1, timeout=3.)
        self.assertTrue(resolved)
        with patch.object(MainWindow, 'refresh', lambda self: None):
            window = MainWindow()
        source = resolved[0]
        timer = QTimer()
        timer.setInterval(20)
        origin, ticks = local_clock(), 0

        def publish():
            nonlocal ticks
            target = int((local_clock()-origin)*self.fs)
            if target > ticks:
                outlet.push_chunk(np.tile(self.eeg['data'], (5,1))[ticks:target].tolist(), origin+(target-1)/self.fs)
                ticks = target

        try:
            window.channel_metadata_cache[source.uid()] = (list(self.names), '')
            selector = window.selectors['EEG']
            selector.blockSignals(True)
            selector.clear()
            selector.addItem(stream_id, source)
            selector.blockSignals(False)
            window.stream_selection_changed('EEG')
            window.connect_stream('EEG')
            timer.timeout.connect(publish)
            timer.start()
            self.assertTrue(self.pump(lambda: getattr(window.workers.get('EEG'), 'active', False)))
            self.assertTrue(window.asr_view.train.isEnabled())
            # At least 60 accepted seconds; startup/rejected windows do not count.
            window.asr_view.train.click()
            self.assertTrue(self.pump(lambda: not window.asr_session.busy))
            self.assertIsNone(window.capture)
            self.assertIsNone(window.loaded_bsl)
            self.assertIsNone(window.loaded_eyc)
            self.assertTrue(window.asr_session.enabled, window.asr_view.status.text())
            training = window.asr_session.training
            self.assertGreaterEqual(len(training['data'])/training['fs'], 60.)
            self.assertIn('preprocessed_data', training)
            self.assertIn('accepted_window_samples', training)
            self.assertEqual(training['data'].shape[1], 4)
            self.assertEqual(training['channels'], self.names)
            self.assertEqual(window.asr_session.model.channels, tuple(self.names))
            window.grab().save(os.path.abspath('.test-tmp/asr-independent-training.png'))
        finally:
            timer.stop()
            window.close()
            self.app.processEvents()

    def test_real_receiver_preserves_raw_and_applies_asr_to_processed(self):
        model = fit_training_asr(self.eeg)
        stream_id = 'asr-test-'+uuid.uuid4().hex
        info = StreamInfo(stream_id, 'EEG', 4, self.fs, 'float32', stream_id)
        channels = info.desc().append_child('channels')
        for name in self.names:
            item = channels.append_child('channel')
            item.append_child_value('label', name)
            item.append_child_value('unit', 'uV')
        outlet = StreamOutlet(info)
        resolved = resolve_byprop('source_id', stream_id, minimum=1, timeout=3.)
        self.assertTrue(resolved)
        receiver = Receiver(resolved[0], 'EEG', list(range(4)), self.names, eeg_asr_model=model)
        errors = []
        receiver.failure.connect(errors.append)
        receiver.start()
        chunks, ticks = [], 0
        origin = local_clock()
        try:
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                target = int((local_clock()-origin)*self.fs)
                if target > ticks:
                    data = self.eeg['data'][ticks:target].copy()
                    at = np.arange(ticks,target)/self.fs
                    data[:,0] += np.where((at>2)&(at<4), 1000*np.sin(2*np.pi*4*at), 0.)
                    outlet.push_chunk(data.tolist(), origin+(target-1)/self.fs)
                    ticks = target
                chunks.extend(receiver.mailbox.drain())
                self.app.processEvents()
                time.sleep(.01)
            self.assertFalse(errors, errors)
            self.assertEqual(receiver.asr_status, 'ASR active')
            self.assertGreater(receiver.asr_processed_samples, 0)
            self.assertLess(time.monotonic()-receiver.asr_last_processed_at, 2.)
            self.assertTrue(chunks)
            # Payload order is raw, processed, names, metrics, fs, times, arrival.
            raw = np.concatenate([c[0] for c in chunks])
            self.assertGreater(np.max(np.abs(raw[:,0])), 800.)
            metrics = [c.metric for c in chunks if c.metric]
            self.assertTrue(metrics)
            self.assertTrue(all(d['_eeg_asr_id'] == model.model_id for d in metrics))
            self.assertTrue(all('_asr' not in d and '_asr_input' not in d for d in metrics))
            self.assertTrue(all(np.isfinite(c[1]).all() for c in chunks))
            cleaned_history, verified = [], 0
            for chunk in chunks:
                cleaned_history.append(chunk.filtered)
                if chunk.metric is None or chunk.metric.get('_partial'):
                    continue
                expected = eeg_metrics(np.concatenate(cleaned_history)[-round(self.fs):],
                                       self.fs, self.names, 10.)
                for name in ('AWI', 'BAR'):
                    self.assertAlmostEqual(chunk.metric[name], expected[name], places=10)
                verified += 1
            self.assertGreater(verified, 3, 'No live metrics verified against ASR-cleaned samples')
        finally:
            receiver.stop()
            self.app.processEvents()

    def test_running_32_channel_stream_restarts_on_asr_toggle_without_metric_holes(self):
        fs, names = SPECS['EEG']
        physiology = SyntheticPhysiology(seed=2026, artifact_level='none')
        baseline = {'data': physiology.generate('EEG', 0, int(60*fs)),
                    'timestamps': np.arange(int(60*fs))/fs, 'fs': fs,
                    'channels': list(names), 'units': ['uV']*len(names)}
        original = analyze_bsl({'EEG': baseline}, 10.)
        stream_id = 'asr-toggle-'+uuid.uuid4().hex
        info = StreamInfo(stream_id, 'EEG', len(names), fs, 'float32', stream_id)
        channels = info.desc().append_child('channels')
        for name in names:
            item = channels.append_child('channel')
            item.append_child_value('label', name)
            item.append_child_value('unit', 'uV')
        outlet = StreamOutlet(info)
        resolved = resolve_byprop('source_id', stream_id, minimum=1, timeout=3.)
        self.assertTrue(resolved)
        source = resolved[0]
        with patch.object(MainWindow, 'refresh', lambda self: None):
            window = MainWindow()
        window.resize(1440, 900)
        window.show()
        physiology = SyntheticPhysiology(seed=42, artifact_level='none')
        ticks, origin = 0, local_clock()
        publisher_stop = threading.Event()
        publisher = None

        def send_samples():
            nonlocal ticks
            # Model an independent device clock. GUI rendering must not delay
            # source publication and create artificial transport gaps in this test.
            while not publisher_stop.wait(.01):
                target = int((local_clock()-origin)*fs)
                while target > ticks:
                    stop = min(target, ticks+round(fs*.05))
                    data = physiology.generate('EEG', ticks, stop-ticks)
                    outlet.push_chunk(data.tolist(), origin+(stop-1)/fs)
                    ticks = stop

        def publish(seconds):
            deadline = time.monotonic()+seconds
            while time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)

        try:
            window.channel_metadata_cache[source.uid()] = (list(names), '')
            selector = window.selectors['EEG']
            selector.blockSignals(True)
            selector.clear()
            selector.addItem(stream_id, source)
            selector.blockSignals(False)
            window.stream_selection_changed('EEG')
            window.apply_calibration('EYC', {'analysis': {'iaf_hz': 10.}})
            window.apply_calibration('BSL', {'analysis': original}, streams={'EEG': baseline})
            window.asr_session.set_training(baseline)
            window.fit_eeg_asr(window.asr_view.settings())
            self.assertTrue(self.pump(lambda: not window.asr_session.busy))
            model = window.asr_session.model
            self.assertIsNotNone(model)
            window.normalization.setCurrentIndex(window.normalization.findData('zscore'))
            origin = local_clock()
            publisher = threading.Thread(target=send_samples, daemon=True)
            publisher.start()
            window.tabs.setCurrentWidget(window.raw_page)
            window.eeg_display_count.setValue(len(names))
            window.connect_stream('EEG')
            publish(2.)
            plain_worker = window.workers['EEG']
            self.assertIsNone(plain_worker.eeg_asr_model)
            window.set_eeg_asr_enabled(True)
            self.assertIn('EEG', window.pending_source_changes)
            publish(5.)
            corrected_worker = window.workers['EEG']
            self.assertIsNot(corrected_worker, plain_worker)
            self.assertEqual(corrected_worker.eeg_asr_model.model_id, model.model_id)
            self.assertFalse(window.pending_source_changes)
            self.assertTrue(window.asr_session.enabled)
            self.assertFalse(window.eeg_reference_pending)
            self.assertEqual(corrected_worker.selected_names, list(names))
            self.assertEqual(window.loaded_bsl['analysis']['source_configurations']['EEG']['asr_model_id'], model.model_id)
            for name in ('AWI', 'BAR'):
                values = window.metric_state.history['EEG', name]
                self.assertGreater(len(values), 4, name)
                self.assertTrue(all(np.isfinite(value) for _, value in values), name)
                self.assertTrue(all(np.diff([at for at, _ in values]) < .85),
                                (name, np.diff([at for at, _ in values]).tolist()))
                value = window.metric_state.latest['EEG'][name]
                self.assertIsNotNone(window.displayed_value('EEG', name, value))
            stamps = np.concatenate([chunk[0] for chunk in window.raw_display.history['EEG']])
            recent = stamps[stamps >= stamps[-1]-2.]
            self.assertLess(np.max(np.diff(recent)), 1.5/fs)
            if window.raw_renderer_mode == 'vispy':
                ring = window.raw_vispy_plots['EEG'].layers['raw'][0].ring
                recent_slots = ring.stamps >= ring.last_time-2.
                missing = np.all(ring.positions[recent_slots] == -10., axis=(1, 2))
                # One sweep-wrap boundary is intentionally disconnected.
                self.assertLess(np.mean(missing), .02)
            window.refresh_asr_indicator(time.monotonic())
            self.assertIn(window.raw_asr_status.text(), ('● ASR monitoring', '● ASR correcting'))
            window.grab().save(os.path.abspath('.test-tmp/asr-toggle-fixed.png'))
            window.tabs.setCurrentWidget(window.metrics_page)
            publish(.7)
            for name in ('AWI', 'BAR'):
                self.assertNotIn('—', window.metric_labels['EEG', name].text())
            window.grab().save(os.path.abspath('.test-tmp/asr-metrics-fixed.png'))
            window.set_eeg_asr_enabled(False)
            self.assertIn('EEG', window.pending_source_changes)
            publish(2.)
            self.assertIsNot(window.workers['EEG'], corrected_worker)
            self.assertIsNone(window.workers['EEG'].eeg_asr_model)
            self.assertEqual(window.loaded_bsl['analysis']['metrics'], original['metrics'])
            self.assertIsNotNone(window.metric_state.latest['EEG']['BAR'])
        finally:
            publisher_stop.set()
            if publisher is not None:
                publisher.join(2.)
            window.close()
            self.app.processEvents()
