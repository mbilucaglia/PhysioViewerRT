"""Source-window provenance carried alongside numeric metric dictionaries."""
from dataclasses import asdict, dataclass
import math


def source_configuration(kind, fs, channels, preprocessing, conversion, units, motion_reference=None):
    """Canonical input metadata for rejecting incompatible baseline statistics."""
    from .processing_filters import validate_preprocessing
    from .source_conversion import SourceConversion
    from .display_units import source_display_unit
    result = {'fs': float(fs), 'channels': [str(name) for name in channels],
            'preprocessing': validate_preprocessing(kind, **(preprocessing or {})),
            'conversion': dict(conversion or SourceConversion().metadata()),
            'units': [source_display_unit([unit]) for unit in units]}
    if motion_reference is not None:
        from .motion_recording import motion_configuration
        result['motion_reference'] = motion_configuration(motion_reference)
    return result


def eeg_configuration(eeg):
    """Canonical EEG metadata shared by live training and calibration replay."""
    return source_configuration('EEG', float(eeg['fs']), list(eeg['channels']),
        eeg.get('preprocessing'), eeg.get('conversion'),
        eeg.get('units') or [''] * len(eeg['channels']), eeg.get('motion_reference'))


@dataclass(frozen=True)
class MetricObservation:
    value: float | None
    window_start: float
    window_end: float
    available_at: float
    unit: str
    pipeline_id: str

    def __post_init__(self):
        if (not all(math.isfinite(v) for v in
                    (self.window_start, self.window_end, self.available_at))
                or self.window_start > self.window_end):
            raise ValueError('Metric source windows must be finite and ordered')

    def metadata(self):
        return {**asdict(self), 'valid': self.value is not None and math.isfinite(self.value)}
