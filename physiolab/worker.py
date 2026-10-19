from PySide6.QtCore import QThread, Signal
from pylsl import StreamInlet, resolve_streams
from .processing import Processor


class Receiver(QThread):
    updated = Signal(str, object, object, object)
    failure = Signal(str)

    def __init__(self, info, kind):
        super().__init__()
        self.info, self.kind = info, kind
        self.active = True

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
            proc = Processor(self.kind, fs, count, names)
            while self.active:
                samples, timestamps = inlet.pull_chunk(timeout=.2, max_samples=1024)
                if not samples:
                    continue
                metric = proc.push(samples)
                self.updated.emit(self.kind, proc.filtered[-int(fs * 5):].copy(), names, metric)
        except Exception as exc:
            self.failure.emit(f'{self.kind}: {exc}')

    def stop(self):
        self.active = False
        self.wait(1500)


def discover():
    return resolve_streams(wait_time=1.0)
