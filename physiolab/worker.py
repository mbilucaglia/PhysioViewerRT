import time
import logging
import threading
from dataclasses import replace
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
from .receiver_state import ReceiverSnapshot, freeze
from .motion_lsl import MotionInput

logger = logging.getLogger(__name__)


class Receiver(QThread):
    failure = Signal(str)
    stream_ready = Signal(str, object, float)
    display_scale_ready = Signal(str, object, str)

    def __init__(self, info, kind, selected_indices, selected_names, preprocessing=None,
                 conversion=None, eeg_asr_model=None, motion_reference=None):
        super().__init__()
        self._control_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._requested_iaf = 10.
        self._requested_monitor = None
        self._status = None
        self.info, self.kind = info, kind
        self.selected_indices = validated_indices(selected_indices, info.channel_count(), kind)
        if len(selected_names) != info.channel_count():
            raise ValueError('Channel label count differs from the source count')
        self.selected_names = [str(selected_names[i]) for i in self.selected_indices]
        self.active = True
        self.last_error = None
        self.iaf_hz = 10.0
        self.preprocessing = dict(preprocessing or {})
        self.conversion = conversion or SourceConversion()
        self.source_units = []
        self.output_units = []
        self.inlet = None
        self.motion_reference = motion_reference
        if motion_reference is not None:
            motion_reference.validate_primary(info, self.selected_indices)
        self.motion_feedback = ('ACC waiting' if motion_reference else 'ACC off', None)
        self.latest_source_timestamp = None
        self.tonic_metadata = None
        self.source_configuration = None
        self.eeg_asr_model = eeg_asr_model if kind == 'EEG' else None
        self.asr_status = 'ASR disabled'
        self.asr_training_monitor = None
        self.asr_processed_samples = 0
        self.asr_last_processed_at = None
        self.asr_last_correction_at = None
        self.reduction_feedback = (None,None,0.,False)
        # Immutable snapshot: processed time, last modification, startup progress,
        # waiting for the first output (also reset after a source gap).
        self.mailbox = ChunkMailbox(info.nominal_srate())
        self._publish_status()

    @property
    def active(self):
        return not self._stop_event.is_set()

    @active.setter
    def active(self, value):
        if value:
            self._stop_event.clear()
        else:
            self._stop_event.set()

    @property
    def iaf_hz(self):
        with self._control_lock:
            return self._requested_iaf

    @iaf_hz.setter
    def iaf_hz(self, value):
        with self._control_lock:
            self._requested_iaf = float(value)

    @property
    def asr_training_monitor(self):
        with self._control_lock:
            return self._requested_monitor

    @asr_training_monitor.setter
    def asr_training_monitor(self, value):
        with self._control_lock:
            self._requested_monitor = value

    def _chunk_controls(self):
        with self._control_lock:
            return self._requested_iaf, self._requested_monitor

    def _publish_status(self):
        configuration = freeze(self.source_configuration)
        preprocessing = freeze(self.preprocessing)
        tonic = freeze(self.tonic_metadata)
        with self._control_lock:
            revision = 0 if self._status is None else self._status.revision + 1
            self._status = ReceiverSnapshot(revision, self.active, configuration,
                preprocessing, tonic, tuple(self.source_units), tuple(self.output_units),
                self.latest_source_timestamp, self.asr_status, self.eeg_asr_model,
                self.asr_processed_samples, self.asr_last_processed_at,
                self.asr_last_correction_at, self.reduction_feedback, self.last_error,
                self.motion_feedback)

    def status_snapshot(self):
        with self._control_lock:
            return self._status

    def run(self):
        motion = None
        try:
            # Use LSL's measured host-clock correction before timestamps enter
            # the shared viewport, retained histories, or calibration capture.
            inlet = StreamInlet(self.info, max_buflen=30, processing_flags=proc_clocksync)
            self.inlet = inlet
            fs = self.info.nominal_srate()
            if fs <= 0:
                raise ValueError('Irregular-rate streams are not supported in MVP')
            count = len(self.selected_indices)
            motion = MotionInput(self.motion_reference, fs, count) if self.motion_reference else None
            motion_transform = motion.transform if motion and self.motion_reference.enabled else None
            names = list(self.selected_names)
            try:
                units = stream_channel_units(inlet.info(timeout=2.), self.selected_indices)
            except Exception:
                logger.warning('Receiver metadata fallback (kind=%s)', self.kind, exc_info=True)
                units = [''] * count
            self.source_units = list(units)
            units = self.conversion.units(units)
            self.output_units = list(units)
            self.source_configuration = source_configuration(
                self.kind, fs, names, self.preprocessing, self.conversion.metadata(), units,
                self.motion_reference.metadata() if motion_transform else None)
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
                             sample_transform=cleaner.process if cleaner else None,
                             timestamp_transform=motion_transform)
            tonic = TonicSCProcessor(unit=unit) if self.kind == 'EDA' else None
            if tonic is not None:
                tonic_processing = dict(proc.preprocessing)
                if motion_transform is not None:
                    tonic_processing['motion_reference'] = self.motion_reference.metadata()
                self.tonic_metadata = sc_pipeline_metadata(
                    tonic, tonic_processing, self.conversion.metadata())
            first_source_timestamp = None
            self._publish_status()
            self.stream_ready.emit(self.kind, names, float(fs))
            while self.active:
                if motion is not None:
                    motion.poll()
                    self.motion_feedback = motion.telemetry()
                # Bound delivery to one metric hop, including after a backlog.
                samples, timestamps = inlet.pull_chunk(
                    timeout=.2, max_samples=max(1, round(fs * METRIC_HOP_SECONDS)))
                if not samples:
                    self._publish_status()
                    continue
                if motion is not None:
                    motion.poll()
                iaf_hz, monitor = self._chunk_controls()
                proc.iaf_hz = iaf_hz
                selected = select_chunk(samples, self.selected_indices)
                timestamps, selected, _ = clean_lsl_chunk(
                    timestamps, selected, selected, self.latest_source_timestamp)
                if not len(timestamps):
                    continue
                if (cleaner is not None and self.latest_source_timestamp is not None
                        and timestamps[0]-self.latest_source_timestamp > max(.25, 3/fs)):
                    cleaner.reset()
                    proc = Processor(self.kind, fs, count, names, iaf_hz=iaf_hz,
                                     preprocessing=self.preprocessing, sample_transform=cleaner.process,
                                     timestamp_transform=motion_transform)
                    first_source_timestamp = None
                self.latest_source_timestamp = float(timestamps[-1])
                if first_source_timestamp is None:
                    first_source_timestamp = float(timestamps[0])
                selected = self.conversion.apply(selected)
                try:
                    metric = proc.push(selected,timestamps=timestamps)
                except ASRError as exc:
                    # A failed cleaner must not terminate raw acquisition.
                    cleaner = self.eeg_asr_model = None
                    self.asr_status = f'ASR bypassed after processing error: {exc}'
                    self.source_configuration = {key: value for key, value in self.source_configuration.items()
                                                 if key != 'asr_model_id'}
                    # NLMS has already consumed these timestamps. Reuse its
                    # captured output when retrying without ASR, never adapt twice.
                    captured_motion = proc.last_motion_chunk
                    proc = Processor(self.kind, fs, count, names, iaf_hz=iaf_hz,
                                     preprocessing=self.preprocessing,
                                     timestamp_transform=(lambda x, ts: captured_motion)
                                     if motion_transform else None)
                    metric = proc.push(selected,timestamps=timestamps)
                    proc.timestamp_transform = motion_transform
                    self._publish_status()
                    self.stream_ready.emit(self.kind, names, float(fs))
                if motion is not None:
                    self.motion_feedback = motion.telemetry()
                reducer = proc.artifact_reducer
                if reducer is not None:
                    previous = self.reduction_feedback
                    warming = reducer.emitted == 0
                    processed_at = time.monotonic() if len(proc.last_filtered_chunk) else previous[0]
                    changed_at = (processed_at if proc.last_reduction_changed else
                                  None if warming else previous[1])
                    self.reduction_feedback = (processed_at,changed_at,reducer.total/fs,warming)
                if not len(proc.last_filtered_chunk):
                    self._publish_status()
                    continue  # Explicit reducer buffer; no fabricated processed samples.
                selected,timestamps = proc.last_raw_chunk,proc.last_timestamps
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
                                f':ASR={self.source_configuration.get("asr_model_id", "off")}'
                                f':ACC={self.source_configuration.get("motion_reference", "off")}').metadata()
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
                self._publish_status()
                self.mailbox.put(AcquisitionChunk(
                    selected.copy(),
                    proc.last_filtered_chunk.copy(),
                    names, metric, float(fs), timestamps, computed_at,
                    motion_cleaned=proc.last_motion_chunk,
                ))
        except Exception as exc:
            logger.exception('Receiver failed (kind=%s)', self.kind)
            self.last_error = f'{self.kind}: {exc}'
            self._publish_status()
            self.failure.emit(self.last_error)
        finally:
            if motion is not None:
                try:
                    motion.close()
                except Exception:
                    logger.warning('ACC inlet cleanup failed', exc_info=True)
            if self.inlet is not None:
                try:
                    self.inlet.close_stream()
                except Exception:
                    logger.warning('Receiver inlet cleanup failed (kind=%s)', self.kind, exc_info=True)
                self.inlet = None
            self._publish_status()

    def request_stop(self):
        # Called from GUI thread: do not block waiting for the inlet timeout.
        self.active = False
        with self._control_lock:
            self._status = replace(self._status, active=False, revision=self._status.revision + 1)

    def stop(self):
        self.request_stop()
        return self.wait(1500)


def discover():
    return resolve_streams(wait_time=1.0)
