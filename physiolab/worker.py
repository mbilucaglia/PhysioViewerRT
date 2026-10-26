import time
from PySide6.QtCore import QThread, Signal
from pylsl import StreamInlet, resolve_streams, proc_clocksync, local_clock
from .processing import Processor, METRIC_HOP_SECONDS
from .channel_selection import validated_indices, select_chunk
from .ingress import ChunkMailbox
from .acquisition_contracts import AcquisitionChunk
from .raw_timing import clean_lsl_chunk
from .display_units import eeg_display_scale, stream_channel_units, source_display_unit
from .source_conversion import SourceConversion
from .metric_observation import MetricObservation, source_configuration
from .physiological_metrics import METRIC_CALCULATORS
from .sc_decomposition import TonicSCProcessor, sc_pipeline_metadata
from .eeg_asr import ASRError, StreamingASR


class Receiver(QThread):
    failure = Signal(str)
    stream_ready = Signal(str, object, float)
    display_scale_ready = Signal(str, object, str)

    def __init__(self, info, kind, selected_indices, selected_names, preprocessing=None,
                 conversion=None, eeg_asr_model=None):
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
        self.tonic_metadata = None
        self.source_configuration = None
        self.eeg_asr_model = eeg_asr_model if kind == 'EEG' else None
        self.asr_status = 'ASR disabled'
        self.asr_training_monitor = None
        self.asr_processed_samples = 0
        self.asr_last_processed_at = None
        self.asr_last_correction_at = None
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
            self.source_configuration = source_configuration(
                self.kind, fs, names, self.preprocessing, self.conversion.metadata(), units)
            if self.kind == 'EEG':
                scale, unit = eeg_display_scale(units)
            else:
                scale, unit = None, source_display_unit(units)
            self.display_scale_ready.emit(self.kind, scale, unit)
            cleaner = None
            if self.eeg_asr_model is not None:
                if self.eeg_asr_model.source_configuration != self.source_configuration:
                    self.eeg_asr_model = None
                    self.asr_status = 'ASR bypassed: EEG configuration differs from ASR training'
                else:
                    cleaner = StreamingASR(self.eeg_asr_model)
                    self.source_configuration = {**self.source_configuration,
                        'asr_model_id': self.eeg_asr_model.model_id}
                    self.asr_status = 'ASR active'
            proc = Processor(self.kind, fs, count, names, iaf_hz=self.iaf_hz,
                             preprocessing=self.preprocessing,
                             sample_transform=cleaner.process if cleaner else None)
            tonic = TonicSCProcessor(unit=unit) if self.kind == 'EDA' else None
            if tonic is not None:
                self.tonic_metadata = sc_pipeline_metadata(
                    tonic, proc.preprocessing, self.conversion.metadata())
            first_source_timestamp = None
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
                if (cleaner is not None and self.latest_source_timestamp is not None
                        and timestamps[0]-self.latest_source_timestamp > max(.25, 3/fs)):
                    cleaner.reset()
                    proc = Processor(self.kind, fs, count, names, iaf_hz=self.iaf_hz,
                                     preprocessing=self.preprocessing, sample_transform=cleaner.process)
                    first_source_timestamp = None
                self.latest_source_timestamp = float(timestamps[-1])
                if first_source_timestamp is None:
                    first_source_timestamp = float(timestamps[0])
                selected = self.conversion.apply(selected)
                try:
                    metric = proc.push(selected)
                except ASRError as exc:
                    # A failed cleaner must not terminate raw acquisition.
                    cleaner = self.eeg_asr_model = None
                    self.asr_status = f'ASR bypassed after processing error: {exc}'
                    self.source_configuration = {key: value for key, value in self.source_configuration.items()
                                                 if key != 'asr_model_id'}
                    proc = Processor(self.kind, fs, count, names, iaf_hz=self.iaf_hz,
                                     preprocessing=self.preprocessing)
                    metric = proc.push(selected)
                    self.stream_ready.emit(self.kind, names, float(fs))
                monitor = self.asr_training_monitor
                if monitor is not None:
                    monitor.push(selected, proc.last_preprocessed_chunk, timestamps)
                if cleaner is not None:
                    self.asr_processed_samples += len(selected)
                    self.asr_last_processed_at = time.monotonic()
                    if cleaner.last_chunk_corrected:
                        self.asr_last_correction_at = self.asr_last_processed_at
                observations = tonic.push(proc.last_filtered_chunk, timestamps, fs) if tonic else []
                if metric is not None or observations:
                    partial = metric is None
                    metric = dict(metric or {})
                    if partial:
                        metric['_partial'] = True
                    if self.kind == 'EEG':
                        metric['_eeg_asr_id'] = self.source_configuration.get('asr_model_id')
                    source_end = float(timestamps[-1])
                    calculator = METRIC_CALCULATORS.get(self.kind)
                    window_seconds = calculator.window_seconds if calculator else 1.
                    metadata = {}
                    for name, value in metric.items():
                        if not name.startswith('_') and name != 'IAF' and (value is None or isinstance(value, (int, float))):
                            metadata[name] = MetricObservation(
                                value, max(first_source_timestamp, source_end-window_seconds+1/fs),
                                source_end, local_clock(), unit if self.kind == 'EDA' else
                                'bpm' if name == 'HR' else 'a.u.',
                                f'{self.kind}:{proc.preprocessing}:IAF={proc.iaf_hz if self.kind == "EEG" else "n/a"}'
                                f':ASR={self.source_configuration.get("asr_model_id", "off")}').metadata()
                    if observations:
                        observation = observations[-1]
                        metric['SCL'] = observation.value
                        metric['_tonic_at'] = observation.window_end
                        metric['_tonic_pipeline'] = self.tonic_metadata['configuration_id']
                        metadata['SCL'] = MetricObservation(
                            observation.value, observation.window_start, observation.window_end,
                            local_clock(), observation.unit,
                            self.tonic_metadata['configuration_id']).metadata()
                    if tonic is not None:
                        metric['_tonic_status'] = tonic.status
                    metric['_observations'] = metadata
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
