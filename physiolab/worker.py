from PySide6.QtCore import QThread, Signal
from pylsl import StreamInlet, resolve_streams
from .processing import Processor


class Receiver(QThread):
    updated = Signal(str, object, object, object, object, float)
    failure = Signal(str)
    samples_received = Signal(str, object, object, object, float)
    stream_ready = Signal(str, object, float)

    def __init__(self, info, kind):
        super().__init__()
        self.info, self.kind = info, kind
        self.active = True
        self.iaf_hz = 10.0

    def run(self):
        try:
            inlet = StreamInlet(self.info, max_buflen=30)
            fs = self.info.nominal_srate()
            if fs <= 0:
                raise ValueError('Irregular-rate streams are not supported in MVP')
            count = self.info.channel_count()
            names = []
            ch = self.info.desc().child('channels').child('channel')
            for i in range(count):
                names.append(ch.child_value('label') or f'Ch{i+1}')
                ch = ch.next_sibling()
            proc = Processor(self.kind, fs, count, names, iaf_hz=self.iaf_hz)
            self.stream_ready.emit(self.kind, names, float(fs))
            while self.active:
                samples, timestamps = inlet.pull_chunk(timeout=.2, max_samples=1024)
                if not samples:
                    continue
                proc.iaf_hz = self.iaf_hz
                self.samples_received.emit(self.kind, samples, timestamps, names, float(fs))
                metric = proc.push(samples)
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
