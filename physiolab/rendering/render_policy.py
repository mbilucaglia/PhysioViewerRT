"""Shared display geometry and sample budgets, independent of Qt and VisPy."""
from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class RawDisplayPolicy:
    channel_spacing: float = 6.
    channel_margin: float = 3.
    fit_limit: float = 2.5
    fit_target: float = 2.3
    max_points: int = 2500
    history_cycles: int = 2
    initial_tail_seconds: float = .35
    tail_overlap_seconds: float = .1
    max_single_channels: int = 8

    def offsets(self, count):
        return self.channel_spacing * np.arange(count, dtype=float)

    def bounds(self, count):
        if count <= 1:
            return (-self.channel_margin,self.channel_margin)
        return (-self.channel_margin,
                max(self.channel_spacing * count, self.channel_margin))

    def span(self, count):
        lower, upper = self.bounds(count)
        return upper - lower

    def normalized_centers(self, count):
        lower, _ = self.bounds(count)
        return (self.offsets(count) - lower) / self.span(count)

    def label_fraction(self, index, count):
        """Channel center measured upwards from the bottom of the viewport."""
        lower, _ = self.bounds(count)
        return (self.channel_spacing * index - lower) / self.span(count)

    def decimation_stride(self, fs, span, max_points=None):
        budget = self.max_points if max_points is None else max_points
        return max(1, math.ceil(fs * span / budget))

    def display_rate(self, fs, duration, max_points=None):
        stride = self.decimation_stride(
            fs, self.history_cycles * duration, max_points)
        return float(fs) / stride


RAW_DISPLAY_POLICY = RawDisplayPolicy()
