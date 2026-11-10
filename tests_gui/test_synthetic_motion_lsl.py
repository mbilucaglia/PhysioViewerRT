"""Actual six-stream simulator discovery, metadata and acquisition with ACC."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import unittest
import uuid
from types import SimpleNamespace
import numpy as np
from PySide6.QtWidgets import QApplication
from pylsl import StreamInlet, resolve_byprop, local_clock
from simulate import start_outlets, stream_specs, publish_until
from physiolab.synthetic import SyntheticPhysiology, SPECS
from physiolab.synthetic_motion import ACC_SPECS
from physiolab.motion_reduction import MotionReference, acc_axes, is_acc_stream
from physiolab.channel_selection import channel_labels
from physiolab.worker import Receiver


class SyntheticMotionLSLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_publisher_preserves_last_sample_timestamps_across_uneven_batches(self):
        chunks = {key: [] for key in stream_specs()}
        outlets = {key: SimpleNamespace(push_chunk=lambda data, last, k=key: chunks[k].append((data, last)))
                   for key in chunks}
        model = SyntheticPhysiology(seed=3, artifact_level='none', motion_level='mild')
        ticks = dict.fromkeys(chunks, 0)
        origin = 12345.
        for elapsed in (.001, .07, .071, .5, 2.07, 17.123, 17.123):
            publish_until(model, outlets, ticks, origin, elapsed)
        expected = SyntheticPhysiology(seed=3, artifact_level='none', motion_level='mild')
        for key, (fs, _) in stream_specs().items():
            received, timestamps = [], []
            for data, last in chunks[key]:
                received.extend(data)
                timestamps.extend(last-np.arange(len(data)-1, -1, -1)/fs)
            count = int(17.123*fs)
            self.assertEqual(len(received), count)
            np.testing.assert_array_equal(timestamps, origin+np.arange(count)/fs)
            truth = (expected.generate_acc(key[:-4], 0, count) if key.endswith('_ACC')
                     else expected.generate(key, 0, count))
            np.testing.assert_allclose(received, truth, atol=2e-5, rtol=1e-6)

    def test_six_discovered_streams_have_matching_clocks_labels_and_contamination(self):
        prefix = 'sim-motion-'+uuid.uuid4().hex+'-'
        outlets = start_outlets(prefix)
        receivers, captured, errors = {}, {}, []
        try:
            sources = {}
            for key in stream_specs():
                found = resolve_byprop('source_id', prefix+key, minimum=1, timeout=3.)
                self.assertEqual(len(found), 1, key)
                sources[key] = found[0]
                inlet = StreamInlet(found[0])
                try:
                    info = inlet.info(timeout=2.)
                    self.assertEqual(channel_labels(info), list(stream_specs()[key][1]))
                    if key.endswith('_ACC'):
                        self.assertTrue(is_acc_stream(info))
                        self.assertEqual(acc_axes(channel_labels(info)), (0, 1, 2))
                        self.assertEqual(info.desc().child_value('associated_source_id'), prefix+key[:-4])
                        self.assertEqual(info.desc().child('channels').child('channel').child_value('unit'), 'm/s^2')
                    else:
                        self.assertEqual(info.desc().child_value('motion_reference_source_id'), prefix+key+'_ACC')
                finally:
                    inlet.close_stream()
            model = SyntheticPhysiology(seed=2026, artifact_level='none', motion_level='strong')
            ticks = dict.fromkeys(stream_specs(), 0)
            discard = {key: SimpleNamespace(push_chunk=lambda *args: None) for key in ticks}
            publish_until(model, discard, ticks, 0., 16.)
            for kind, (fs, names) in SPECS.items():
                worker = Receiver(sources[kind], kind, list(range(len(names))), list(names),
                    preprocessing={'notch': False},
                    motion_reference=MotionReference(sources[kind+'_ACC'], (0, 1, 2), True))
                worker.failure.connect(errors.append)
                receivers[kind], captured[kind] = worker, []
                worker.start()
            origin = local_clock()-16.
            deadline = local_clock()+8.
            active = set()
            while local_clock() < deadline:
                publish_until(model, outlets, ticks, origin, local_clock()-origin)
                for kind, worker in receivers.items():
                    captured[kind].extend(worker.mailbox.drain())
                    if worker.status_snapshot().motion_feedback[0] == 'ACC NLMS active':
                        active.add(kind)
                self.app.processEvents()
                time.sleep(.02)
            self.assertFalse(errors, errors)
            self.assertEqual(active, set(SPECS))
            for kind, worker in receivers.items():
                fs, names = SPECS[kind]
                truth = SyntheticPhysiology(seed=2026, artifact_level='none', motion_level='strong')
                expected = truth.generate(kind, 0, ticks[kind])
                self.assertTrue(captured[kind])
                corrections = []
                for chunk in captured[kind]:
                    indices = np.rint((chunk.timestamps-origin)*fs).astype(int)
                    np.testing.assert_allclose(chunk.raw, expected[indices], atol=3e-5)
                    self.assertEqual(chunk.raw.shape, chunk.motion_cleaned.shape)
                    self.assertTrue(np.isfinite(chunk.filtered).all())
                    corrections.append(np.max(np.abs(chunk.motion_cleaned-chunk.raw)))
                self.assertGreater(max(corrections), .01, kind)
                config = worker.status_snapshot().source_configuration['motion_reference']
                self.assertEqual(config['source_id'], prefix+kind+'_ACC')
                self.assertEqual(config['fs'], ACC_SPECS[kind][0])
        finally:
            for worker in receivers.values():
                self.assertTrue(worker.stop())
            outlets.clear()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
