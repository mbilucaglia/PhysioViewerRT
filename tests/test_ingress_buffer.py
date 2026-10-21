"""Ingestion and processing buffer regression tests; no Qt event loop needed."""
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np

from physiolab.ingress import ChunkMailbox
from physiolab.signal_buffer import SampleRing
from physiolab.performance import PerformanceMonitor
from physiolab.processing import Processor


class SampleRingTests(unittest.TestCase):
    def test_ring_preserves_time_order_and_wraps(self):
        ring = SampleRing(5, 2)
        ring.append(np.arange(6.).reshape(3, 2))
        np.testing.assert_array_equal(ring.tail(9), [[0, 1], [2, 3], [4, 5]])
        ring.append(np.arange(6., 14.).reshape(4, 2))
        np.testing.assert_array_equal(
            ring.tail(5), [[4, 5], [6, 7], [8, 9], [10, 11], [12, 13]]
        )
        ring.append(np.arange(20., 40.).reshape(10, 2))
        np.testing.assert_array_equal(
            ring.tail(10), np.arange(30., 40.).reshape(5, 2)
        )
        self.assertEqual(len(ring), 5)

    def test_empty_and_channel_validation(self):
        ring = SampleRing(10, 1)
        self.assertEqual(ring.tail(10).shape, (0, 1))
        with self.assertRaises(ValueError):
            ring.append(np.zeros((4, 2)))
        with self.assertRaises(ValueError):
            SampleRing(0, 1)


class MailboxTests(unittest.TestCase):
    def chunk(self, count, metric=None):
        samples = np.arange(count, dtype=float)[:, None]
        return (samples, samples * 2, ['EDA'], metric, 32., list(range(count)))

    def test_order_and_metric_pairing(self):
        box = ChunkMailbox(32, max_seconds=5)
        for i in range(20):
            box.put(self.chunk(5, {'SCL': i}))
        drained = box.drain(max_chunks=8)
        self.assertEqual([x[3]['SCL'] for x in drained], list(range(8)))
        self.assertEqual(box.stats()['queued_chunks'], 12)
        self.assertEqual(len(box.drain(max_chunks=40)), 12)
        self.assertEqual(box.stats()['queued_samples'], 0)

    def test_queue_stays_bounded_under_gui_pause(self):
        box = ChunkMailbox(32, max_seconds=2.)
        for i in range(100):
            box.put(self.chunk(8, {'SCL': i}))
        stats = box.stats()
        self.assertLessEqual(stats['queued_samples'], max(1024, 2 * 32))
        self.assertGreaterEqual(stats['dropped_samples'], 0)
        self.assertEqual(sum(len(x[0]) for x in box.drain(max_chunks=200)),
                         stats['queued_samples'])
        with self.assertRaises(ValueError):
            box.drain(0)

    def test_concurrent_producer_consumer(self):
        box = ChunkMailbox(256, max_seconds=75.)
        def produce():
            for index in range(100):
                box.put(self.chunk(4, {'SCL': index}))
        producer = threading.Thread(target=produce)
        producer.start()
        consumed = []
        while producer.is_alive() or box.stats()['queued_chunks']:
            consumed.extend(box.drain(32))
        producer.join()
        self.assertEqual(len(consumed), 100)
        self.assertEqual([entry[3]['SCL'] for entry in consumed],
                         list(range(100)))


class ProcessorRingTests(unittest.TestCase):
    def test_chunk_order_does_not_change_filtered_signal(self):
        fs = 128
        t = np.arange(fs * 12) / fs
        eeg = np.column_stack((
            np.sin(2 * np.pi * 10 * t), np.sin(2 * np.pi * 18 * t)
        ))
        whole = Processor('EEG', fs, 2, ['F3', 'F4'])
        chunks = Processor('EEG', fs, 2, ['F3', 'F4'])
        whole.push(eeg)
        for i in range(0, len(eeg), 7):
            chunks.push(eeg[i:i+7])
        np.testing.assert_allclose(chunks.filtered, whole.filtered, atol=1e-10)
        np.testing.assert_allclose(chunks.raw, eeg, atol=1e-12)
        self.assertEqual(chunks.last_filtered_chunk.shape[1], 2)


class ProfileTests(unittest.TestCase):
    def test_writes_only_aggregate_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'profile.jsonl'
            monitor = PerformanceMonitor(enabled=True, path=log, interval=0.)
            monitor.measure('gui_timer_total', .002)
            monitor.maybe_flush({'EEG': {'queued_chunks': 1}})
            self.assertIn('gui_timer_total', log.read_text())
            self.assertIn('queued_chunks', log.read_text())


if __name__ == '__main__':
    unittest.main()
