from PySide6.QtCore import QThread, Signal
from pylsl import StreamInlet, resolve_streams
from .processing import Processor
from .channel_selection import validated_indices, select_chunk
from .ingress import ChunkMailbox


class Receiver(QThread):
    failure = Signal(str)
    stream_ready = Signal(str, object, float)

    def __init__(self, info, kind, selected_indices, selected_names):
        super().__init__()
        self.info, self.kind = info, kind
        self.selected_indices = validated_indices(selected_indices, info.channel_count(), kind)
        if len(selected_names) != info.channel_count():
            raise ValueError('Channel label count differs from the source count')
        self.selected_names = [str(selected_names[i]) for i in self.selected_indices]
        self.active = True
        self.iaf_hz = 10.0
        self.inlet = None
        self.latest_source_timestamp = None
        self.mailbox = ChunkMailbox(info.nominal_srate())

    def run(self):
        try:
            inlet = StreamInlet(self.info, max_buflen=30)
            self.inlet = inlet
            fs = self.info.nominal_srate()
            if fs <= 0:
                raise ValueError('Irregular-rate streams are not supported in MVP')
            count = len(self.selected_indices)
            names = list(self.selected_names)
            proc = Processor(self.kind, fs, count, names, iaf_hz=self.iaf_hz)
            self.stream_ready.emit(self.kind, names, float(fs))
            while self.active:
                samples, timestamps = inlet.pull_chunk(timeout=.2, max_samples=1024)
                if not samples:
                    continue
                self.latest_source_timestamp = float(timestamps[-1])
                proc.iaf_hz = self.iaf_hz
                selected = select_chunk(samples, self.selected_indices)
                metric = proc.push(selected)
                self.mailbox.put((
                    selected.copy(),
                    proc.last_filtered_chunk.copy(),
                    names, metric, float(fs), timestamps,
                ))
        except Exception as exc:
            self.failure.emit(f'{self.kind}: {exc}')
        finally:
            if self.inlet is not None:
                try:
                    self.inlet.close_stream()
                except Exception:
                    pass
                self.inlet = None

    def request_stop(self):
        # Called from GUI thread: do not block waiting for the inlet timeout.
        self.active = False

    def stop(self):
        self.request_stop()
        return self.wait(1500)


def discover():
    return resolve_streams(wait_time=1.0)
