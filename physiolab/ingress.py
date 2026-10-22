"""Bounded, thread-safe LSL-to-GUI mailbox.

Acquisition never enqueues a Qt GUI callback per LSL chunk. The GUI drains
batches on its own clock; both raw data and metric observations stay paired.
The queue retains a bounded period of input during temporary GUI stalls.
"""
from collections import deque
import threading


class ChunkMailbox:
    def __init__(self, fs, max_seconds=75.0):
        self._lock = threading.Lock()
        self._items = deque()
        self._samples = 0
        self._limit = max(1024, int(fs * max_seconds))
        self.dropped_samples = 0

    def put(self, chunk):
        """Enqueue an AcquisitionChunk; its first item is the sample array."""
        count = len(chunk[0])
        with self._lock:
            self._items.append(chunk)
            self._samples += count
            while len(self._items) > 1 and self._samples > self._limit:
                removed = self._items.popleft()
                size = len(removed[0])
                self._samples -= size
                self.dropped_samples += size

    def drain(self, max_chunks=128):
        if max_chunks < 1:
            raise ValueError('max_chunks must be positive')
        with self._lock:
            result = []
            while self._items and len(result) < max_chunks:
                item = self._items.popleft()
                self._samples -= len(item[0])
                result.append(item)
            return result

    def stats(self):
        with self._lock:
            return {'queued_chunks': len(self._items),
                    'queued_samples': self._samples,
                    'dropped_samples': self.dropped_samples}
