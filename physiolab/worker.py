from PySide6.QtCore import QThread, Signal
from pylsl import StreamInlet, resolve_streams
from .processing import Processor
from .channel_selection import channel_labels, validated_indices, select_chunk


class Receiver(QThread):
    updated = Signal(str, object, object, object, object, float)
    failure = Signal(str)
    samples_received = Signal(str, object, object, object, float)
    stream_ready = Signal(str, object, float)

    def __init__(self, info, kind, selected_indices, selected_names):
        super().__init__()
        self.info, self.kind = info, kind
        self.selected_indices = validated_indices(selected_indices, info.channel_count(), kind)
        self.selected_names = [str(label) for label in selected_names]
        if len(self.selected_names) != len(self.selected_indices):
            raise ValueError('Selected channel labels and indices differ')
        self.active = True
        self.iaf_hz = 10.0

    def run(self):
        try:
            inlet = StreamInlet(self.info, max_buflen=30)
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
                proc.iaf_hz = self.iaf_hz
                selected = select_chunk(samples, self.selected_indices)
                self.samples_received.emit(self.kind, selected, timestamps, names, float(fs))
                metric = proc.push(selected)
                count_plot = max(1, int(fs * 5))
                self.updated.emit(
                    self.kind,
                    proc.raw[-count_plot:].copy(),
                    proc.filtered[-count_plot:].copy(),
                    names, metric, float(fs)
                )
        except Exception as exc:
            self.failure.emit(f'{self.kind}: {exc}')

    def stop(self):
        self.active = False
        self.wait(1500)


def discover():
    return resolve_streams(wait_time=1.0)
