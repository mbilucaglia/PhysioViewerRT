"""Adaptive training decisions with explicit time and acquisition status."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TrainingPolicy:
    minimum_seconds: float
    deadline: float
    running: bool = False
    error: str = ''
    model: Any = None
    recording: Any = None
    cancelled: bool = False
    next_seconds: float = field(init=False)

    def __post_init__(self):
        self.next_seconds = self.minimum_seconds

    def action(self, status, now, *, source_available=True, interrupted=False):
        if self.cancelled or interrupted or not source_available or now > self.deadline:
            return 'stop'
        accepted = status['accepted_seconds']
        if (not self.running and self.next_seconds > accepted
                and status['accepted_samples'] >= status['maximum_samples']):
            return 'stop'
        return 'fit' if not self.running and accepted >= self.next_seconds else 'wait'

    def start_fit(self, recording):
        self.running, self.recording = True, recording

    def complete(self, model, error, accepted_seconds):
        self.running = False
        if self.cancelled:
            return False
        if error is not None:
            self.error = error
            self.next_seconds = accepted_seconds + 10.
            return False
        self.model = model
        return True

    def cancel(self):
        self.cancelled = True
