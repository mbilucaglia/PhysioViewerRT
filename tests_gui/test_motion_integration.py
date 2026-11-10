"""ACC controls, real LSL acquisition, fallback and receiver cleanup."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
import uuid
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from pylsl import StreamInfo, StreamOutlet, resolve_byprop, local_clock
from physiolab.gui import MainWindow
from physiolab.motion_reduction import MotionReference
from physiolab.worker import Receiver
from physiolab.calibration_session import CalibrationSession
from physiolab.processing import Processor
from physiolab.asr_tasks import fit_training_asr, matched_recording, calibration_references
from physiolab.metric_observation import eeg_configuration
from physiolab.asr_session import ASRSession
from tests import test_motion_calibration as motion_fixtures


class MotionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_asr_training_and_reference_replay_share_the_cleaned_input(self):
        eeg = motion_fixtures.MotionCalibrationTests.eeg()
        expected = Processor('EEG', eeg['fs'], 2, eeg['channels'], preprocessing=eeg['preprocessing'])
        pieces = []
        for start in range(0, len(eeg['data']), 64):
            expected.push(eeg['motion_cleaned'][start:start+64])
            pieces.append(expected.last_filtered_chunk.copy())
        preprocessed = np.concatenate(pieces)
        with patch('physiolab.asr_tasks.fit_asr', return_value='model') as fitter:
            self.assertEqual(fit_training_asr(eeg), 'model')
            np.testing.assert_array_equal(fitter.call_args.args[0], preprocessed)
            self.assertEqual(fitter.call_args.args[3]['motion_reference'], eeg['motion_reference'])
            accepted = {k: v for k, v in eeg.items() if k != 'motion_cleaned'}
            accepted.update(preprocessed_data=preprocessed, accepted_window_samples=[128]*60)
            self.assertEqual(fit_training_asr(accepted), 'model')
            np.testing.assert_array_equal(fitter.call_args.args[0], preprocessed)
        session = ASRSession()
        session.set_training(accepted)
        live = eeg_configuration(eeg)
        self.assertTrue(session.availability(live)[0])
        result = calibration_references(eeg, eeg, {}, 8., None, live)
        self.assertAlmostEqual(result['iaf_hz'], 10., delta=.03)
        self.assertEqual(result['bsl']['source_configurations']['EEG'], live)
        without = {k: v for k, v in live.items() if k != 'motion_reference'}
        self.assertFalse(session.availability(without)[0])
        replay_raw = matched_recording(eeg, without)
        self.assertNotIn('motion_reference', replay_raw)
        self.assertNotIn('motion_cleaned', replay_raw)
        with self.assertRaisesRegex(ValueError, 'ACC cleaning'):
            matched_recording(replay_raw, live)

    def test_gui_capture_forwards_raw_and_post_nlms_payload(self):
        from types import SimpleNamespace
        from physiolab.acquisition_contracts import AcquisitionChunk
        from physiolab.ingress import ChunkMailbox
        with patch.object(MainWindow, 'refresh', lambda self: None):
            window = MainWindow()
        window.timer.stop()
        eeg = motion_fixtures.MotionCalibrationTests.eeg()
        window.capture = CalibrationSession('EYC', {'EEG': eeg}, time.monotonic()+60.)
        mailbox = ChunkMailbox(eeg['fs'])
        chunk = AcquisitionChunk(eeg['data'][:128], eeg['motion_cleaned'][:128], eeg['channels'],
            None, eeg['fs'], eeg['timestamps'][:128], time.monotonic(), eeg['motion_cleaned'][:128])
        mailbox.put(chunk)
        window.workers['EEG'] = SimpleNamespace(mailbox=mailbox)
        try:
            with patch.object(window, 'receive'):
                window.poll_receivers()
            captured = window.capture.finish(minimum_seconds=1.)['EEG']
            np.testing.assert_array_equal(captured['data'], chunk.raw)
            np.testing.assert_array_equal(captured['motion_cleaned'], chunk.motion_cleaned)
        finally:
            window.capture = None
            window.workers.clear()
            window.close()
            self.app.processEvents()

    def test_asr_failure_reuses_nlms_output_without_adapting_twice(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from physiolab.eeg_asr import ASRError
        from physiolab.source_conversion import SourceConversion
        from physiolab.metric_observation import source_configuration
        primary = StreamInfo('EEG', 'EEG', 1, 100, 'float32', 'fallback-eeg')
        acc = StreamInfo('ACC', 'ACC', 3, 50, 'float32', 'fallback-acc')
        reference = MotionReference(acc, (0, 1, 2), True)
        configuration = source_configuration('EEG', 100, ['O1'], {'notch': False},
                                            SourceConversion().metadata(), [''], reference.metadata())
        model = SimpleNamespace(source_configuration=configuration, model_id='test-model')
        worker = Receiver(primary, 'EEG', [0], ['O1'], preprocessing={'notch': False},
                          eeg_asr_model=model, motion_reference=reference)
        raw = np.sin(np.arange(50))[:, None]
        stamps = 100+np.arange(50)/100
        calls = []
        def motion_transform(samples, timestamps):
            calls.append(timestamps.copy())
            return samples*.25
        motion = SimpleNamespace(transform=motion_transform, poll=lambda: None,
            telemetry=lambda: ('ACC NLMS active', None), close=lambda: None)
        def pull(**kwargs):
            if calls:
                worker.request_stop()
                return [], []
            return raw.tolist(), stamps.tolist()
        inlet = SimpleNamespace(info=lambda timeout: primary, pull_chunk=pull, close_stream=lambda: None)
        cleaner = SimpleNamespace(process=Mock(side_effect=ASRError('test ASR failure')))
        with patch('physiolab.worker.StreamInlet', return_value=inlet), \
                patch('physiolab.worker.MotionInput', return_value=motion), \
                patch('physiolab.worker.StreamingASR', return_value=cleaner):
            worker.run()
        self.assertIsNone(worker.last_error)
        self.assertEqual(len(calls), 1)
        chunk = worker.mailbox.drain()[0]
        np.testing.assert_array_equal(chunk.motion_cleaned, raw*.25)
        np.testing.assert_array_equal(chunk.raw, raw)
        self.assertIn('bypassed', worker.status_snapshot().asr_status)

    def test_independent_controls_discovery_mapping_and_refresh(self):
        with patch.object(MainWindow, 'refresh', lambda self: None):
            window = MainWindow()
        try:
            acc = StreamInfo('Watch ACC', 'Accelerometer', 3, 50, 'float32', 'acc-test')
            mixed = StreamInfo('Mixed', 'EEG', 6, 100, 'float32', 'mixed-test')
            acc.uid = lambda: 'acc-test'
            mixed.uid = lambda: 'mixed-test'
            for control in window.motion_controls.values():
                control.set_streams([mixed, acc])
                self.assertIsNone(control.reference())
                self.assertEqual(control.source.itemData(1).name(), 'Watch ACC')
            control = window.motion_controls['PPG']
            with patch.object(window, 'queue_lsl_task'), patch.object(window, 'schedule_source_change') as changed:
                control.source.setCurrentIndex(2)
                control.set_labels('mixed-test', ['PPG', 'other', 'Acc Z', 'Acc X', 'Acc Y', 'aux'])
                control.enabled.setChecked(True)
                self.assertEqual(control.reference().indices, (3, 4, 2))
                changed.assert_called_with('PPG')
            self.assertIsNone(window.motion_controls['EEG'].reference())
            signature = control.signature()
            control.set_streams([])
            self.assertEqual(control.signature(), signature)
            window.resize(1440, 1000)
            window.show()
            self.app.processEvents()
            for axis in control.axes:
                self.assertGreater(axis.lineEdit().width(), 15)
            control.axes[0].setValue(control.axes[1].value())
            with self.assertRaises(ValueError):
                control.reference()
        finally:
            window.close()
            self.app.processEvents()

    def test_real_lsl_three_modalities_and_acc_dropout(self):
        prefix = 'motion-'+uuid.uuid4().hex
        acc_info = StreamInfo(prefix+'ACC', 'Accelerometer', 3, 50, 'float32', prefix+'ACC')
        acc_out = StreamOutlet(acc_info)
        acc = resolve_byprop('source_id', prefix+'ACC', minimum=1, timeout=3.)[0]
        outlets, workers, captured = {}, {}, {}
        errors = []
        for kind, fs in [('EEG', 100), ('PPG', 64), ('EDA', 32)]:
            info = StreamInfo(prefix+kind, kind, 1, fs, 'float32', prefix+kind)
            outlets[kind] = StreamOutlet(info)
            source = resolve_byprop('source_id', prefix+kind, minimum=1, timeout=3.)[0]
            workers[kind] = Receiver(source, kind, [0], [kind],
                preprocessing=dict(preset='default', notch=False),
                motion_reference=MotionReference(acc, (0, 1, 2), True))
            workers[kind].failure.connect(errors.append)
            captured[kind] = []
            workers[kind].start()
        ticks = dict(ACC=0, EEG=0, PPG=0, EDA=0)
        origin = local_clock()
        active = set()
        try:
            while local_clock()-origin < 7.:
                elapsed = local_clock()-origin
                for kind, fs in [('ACC', 50), ('EEG', 100), ('PPG', 64), ('EDA', 32)]:
                    target = int(elapsed*fs)
                    if target <= ticks[kind]:
                        continue
                    t = np.arange(ticks[kind], target)/fs
                    if kind == 'ACC':
                        if elapsed < 5.:
                            values = np.column_stack((np.sin(2*np.pi*.9*t), np.cos(t), np.sin(3*t)))
                            acc_out.push_chunk(values.tolist(), origin+(target-1)/fs)
                    else:
                        values = (5 + np.sin(2*np.pi*1.3*t)+np.sin(2*np.pi*.9*t))[:, None]
                        outlets[kind].push_chunk(values.tolist(), origin+(target-1)/fs)
                        captured[kind].extend(workers[kind].mailbox.drain())
                        if workers[kind].status_snapshot().motion_feedback[0] == 'ACC NLMS active':
                            active.add(kind)
                    ticks[kind] = target
                self.app.processEvents()
                time.sleep(.01)
            self.assertFalse(errors, errors)
            self.assertEqual(active, {'EEG', 'PPG', 'EDA'})
            for kind, worker in workers.items():
                self.assertTrue(worker.isRunning())
                self.assertIn('stale', worker.status_snapshot().motion_feedback[0])
                self.assertIn('motion_reference', worker.status_snapshot().source_configuration)
                self.assertTrue(captured[kind], kind)
                for chunk in captured[kind]:
                    t = np.rint((np.asarray(chunk.timestamps)-origin)*chunk.fs)/chunk.fs
                    expected = 5+np.sin(2*np.pi*1.3*t)+np.sin(2*np.pi*.9*t)
                    np.testing.assert_allclose(chunk.raw[:, 0], expected, atol=3e-5)
                    self.assertEqual(chunk.raw.shape, chunk.filtered.shape)
                    self.assertEqual(chunk.raw.shape, chunk.motion_cleaned.shape)
                    self.assertTrue(np.isfinite(chunk.motion_cleaned).all())
                replay = Processor(kind, worker.info.nominal_srate(), 1, [kind],
                                   preprocessing=worker.preprocessing)
                for chunk in captured[kind]:
                    replay.push(chunk.motion_cleaned, chunk.timestamps)
                    np.testing.assert_allclose(replay.last_filtered_chunk, chunk.filtered, atol=1e-12)
        finally:
            for worker in workers.values():
                self.assertTrue(worker.stop())
                self.assertIsNone(worker.inlet)
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
