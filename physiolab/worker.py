import time
from PySide6.QtCore import QThread, Signal
from pylsl import StreamInlet, resolve_streams, proc_clocksync
from .processing import Processor, METRIC_HOP_SECONDS
from .channel_selection import validated_indices, select_chunk
from .ingress import ChunkMailbox
from .acquisition_contracts import AcquisitionChunk
from .raw_timing import clean_lsl_chunk
from .display_units import eeg_display_scale, stream_channel_units, source_display_unit
from .source_conversion import SourceConversion


class Receiver(QThread):
    failure = Signal(str)
    stream_ready = Signal(str, object, float)
    display_scale_ready = Signal(str, object, str)

    def __init__(self, info, kind, selected_indices, selected_names, preprocessing=None,
                 conversion=None):
        super().__init__()
        self.info, self.kind = info, kind
        self.selected_indices = validated_indices(selected_indices, info.channel_count(), kind)
        if len(selected_names) != info.channel_count():
            raise ValueError('Channel label count differs from the source count')
        self.selected_names = [str(selected_names[i]) for i in self.selected_indices]
        self.active = True
        self.iaf_hz = 10.0
        self.preprocessing = dict(preprocessing or {})
        self.conversion = conversion or SourceConversion()
        self.source_units = []
        self.output_units = []
        self.inlet = None
        self.latest_source_timestamp = None
        self.mailbox = ChunkMailbox(info.nominal_srate())

    def run(self):
        try:
            # Use LSL's measured host-clock correction before timestamps enter
            # the shared viewport, retained histories, or calibration capture.
            inlet = StreamInlet(self.info, max_buflen=30, processing_flags=proc_clocksync)
            self.inlet = inlet
            fs = self.info.nominal_srate()
            if fs <= 0:
                raise ValueError('Irregular-rate streams are not supported in MVP')
            count = len(self.selected_indices)
            names = list(self.selected_names)
            try:
                units = stream_channel_units(inlet.info(timeout=2.), self.selected_indices)
            except Exception:
                units = [''] * count
            self.source_units = list(units)
            units = self.conversion.units(units)
            self.output_units = list(units)
            if self.kind == 'EEG':
                scale, unit = eeg_display_scale(units)
            else:
                scale, unit = None, source_display_unit(units)
            self.display_scale_ready.emit(self.kind, scale, unit)
            proc = Processor(self.kind, fs, count, names, iaf_hz=self.iaf_hz,
                             preprocessing=self.preprocessing)
            self.stream_ready.emit(self.kind, names, float(fs))
            while self.active:
                # Bound delivery to one metric hop, including after a backlog.
                samples, timestamps = inlet.pull_chunk(
                    timeout=.2, max_samples=max(1, round(fs * METRIC_HOP_SECONDS)))
                if not samples:
                    continue
                proc.iaf_hz = self.iaf_hz
                selected = select_chunk(samples, self.selected_indices)
                timestamps, selected, _ = clean_lsl_chunk(
                    timestamps, selected, selected, self.latest_source_timestamp)
                if not len(timestamps):
                    continue
                self.latest_source_timestamp = float(timestamps[-1])
                selected = self.conversion.apply(selected)
                metric = proc.push(selected)
                computed_at = time.monotonic()
                self.mailbox.put(AcquisitionChunk(
                    selected.copy(),
                    proc.last_filtered_chunk.copy(),
                    names, metric, float(fs), timestamps, computed_at,
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
