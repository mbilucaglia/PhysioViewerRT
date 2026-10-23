"""Shared application policy; presentation settings do not alter acquisition."""
from dataclasses import dataclass
import math
from numbers import Integral, Real


@dataclass(frozen=True)
class ViewerSettings:
    display_fps: int = 30
    presentation_delay_seconds: float = .25
    stale_source_seconds: float = 1.
    history_seconds: float = 300.
    default_view_seconds: float = 5.
    default_eeg_display_channels: int = 8
    asr_training_seconds: float = 45.
    metric_history_capacity: int = 900
    ingress_chunks_per_tick: int = 32
    source_change_debounce_ms: int = 150
    gain_minimum: float = .05
    gain_maximum: float = 50.
    gain_step: float = 1.2

    def __post_init__(self):
        for name, value in vars(self).items():
            if (isinstance(value, bool) or not isinstance(value, Real)
                    or not math.isfinite(value) or value <= 0):
                raise ValueError(f'{name} must be finite and positive')
        count_fields = ('display_fps', 'default_eeg_display_channels', 'metric_history_capacity',
                        'ingress_chunks_per_tick', 'source_change_debounce_ms')
        for name in count_fields:
            if not isinstance(getattr(self, name), Integral):
                raise ValueError(f'{name} must be an integer')
        if self.asr_training_seconds < 30:
            raise ValueError('ASR training must record at least 30 seconds')
        if self.default_view_seconds > self.history_seconds:
            raise ValueError('Default view cannot exceed retained history')
        if self.gain_minimum >= self.gain_maximum:
            raise ValueError('Minimum gain must be less than maximum gain')
        if self.gain_step <= 1:
            raise ValueError('Multiplicative gain step must exceed one')

    @property
    def timer_interval_ms(self):
        return max(1, round(1000 / self.display_fps))


DEFAULT_VIEWER_SETTINGS = ViewerSettings()
