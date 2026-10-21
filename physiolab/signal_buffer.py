"""Bounded O(chunk size) sample history for online signal processing."""
import numpy as np


class SampleRing:
    def __init__(self, capacity, channels):
        self.capacity = int(capacity)
        self.channels = int(channels)
        if self.capacity < 1 or self.channels < 1:
            raise ValueError('Positive capacity and channel count required')
        self._data = np.empty((self.capacity, self.channels), dtype=float)
        self._write = 0
        self._count = 0

    def __len__(self):
        return self._count

    def append(self, chunk):
        data = np.asarray(chunk, dtype=float)
        if data.ndim != 2 or data.shape[1] != self.channels:
            raise ValueError('Sample ring channel mismatch')
        n = len(data)
        if not n:
            return
        if n >= self.capacity:
            self._data[:] = data[-self.capacity:]
            self._write = 0
            self._count = self.capacity
            return
        first = min(n, self.capacity - self._write)
        self._data[self._write:self._write+first] = data[:first]
        if n > first:
            self._data[:n-first] = data[first:]
        self._write = (self._write + n) % self.capacity
        self._count = min(self.capacity, self._count + n)

    def tail(self, count):
        n = max(0, min(int(count), self._count))
        if n == 0:
            return np.empty((0, self.channels), dtype=float)
        start = (self._write - n) % self.capacity
        if start + n <= self.capacity:
            return self._data[start:start+n].copy()
        split = self.capacity - start
        return np.concatenate((self._data[start:], self._data[:n-split]))
