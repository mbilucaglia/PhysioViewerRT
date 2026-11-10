"""Optional ACC inlet owned and polled exclusively by its primary receiver."""
import numpy as np
from pylsl import StreamInlet, proc_clocksync, local_clock
from .motion_reduction import MotionCanceller


class MotionInput:
    def __init__(self, reference, fs, channels):
        self.reference = reference
        self.canceller = MotionCanceller(fs, channels, reference.info.nominal_srate())
        self.inlet = None
        self.error = None

    def poll(self):
        try:
            if self.inlet is None:
                self.inlet = StreamInlet(self.reference.info, max_buflen=40,
                                         processing_flags=proc_clocksync)
            # Bounded drain, including high-rate sources. Never wait for ACC.
            for _ in range(8):
                samples, stamps = self.inlet.pull_chunk(timeout=0., max_samples=4096)
                if not stamps:
                    break
                self.canceller.append(np.asarray(samples)[:, self.reference.indices], stamps)
            self.error = None
        except Exception as exc:
            self.error = f'ACC bypass: {exc}'
            self.canceller.reset()
            self.canceller.times = np.empty(0)
            self.canceller.values = np.empty((0, 3))

    def transform(self, samples, timestamps):
        return self.canceller.process(samples, timestamps)

    def telemetry(self):
        state = self.error or (self.canceller.status if self.reference.enabled else 'ACC monitor only')
        if self.error is None and (not len(self.canceller.times) or
                local_clock()-self.canceller.times[-1] > self.canceller.max_age):
            state = 'ACC bypass: missing/stale reference' if self.reference.enabled else 'ACC monitor: waiting/stale'
        return state, self.canceller.latest

    def close(self):
        if self.inlet is not None:
            self.inlet.close_stream()
            self.inlet = None
