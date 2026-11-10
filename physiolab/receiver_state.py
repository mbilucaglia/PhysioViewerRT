"""Immutable acquisition telemetry; independent of Qt and LSL."""
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value):
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class ReceiverSnapshot:
    revision: int
    active: bool
    configuration: Any
    preprocessing: Any
    tonic_configuration: Any
    source_units: tuple
    output_units: tuple
    latest_source_timestamp: float | None
    asr_status: str
    eeg_asr_model: Any
    asr_processed_samples: int
    asr_last_processed_at: float | None
    asr_last_correction_at: float | None
    reduction_feedback: tuple
    last_error: str | None
    motion_feedback: tuple = ('ACC off', None)

    @property
    def source_configuration(self):
        # Canonical comparisons use lists; return an independent compatibility view.
        return thaw(self.configuration)

    @property
    def tonic_metadata(self):
        return thaw(self.tonic_configuration)


def receiver_view(worker):
    """One snapshot per decision; also accept plain telemetry test doubles."""
    if worker is None:
        return None
    snapshot = getattr(worker, 'status_snapshot', None)
    return snapshot() if snapshot is not None else worker
