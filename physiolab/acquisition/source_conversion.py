"""Explicit sensor calibration, applied once at the acquisition boundary."""
from dataclasses import dataclass, asdict
import math

import numpy as np


@dataclass(frozen=True)
class SourceConversion:
    gain: float = 1.
    offset: float = 0.
    output_unit: str = ''

    def __post_init__(self):
        if not math.isfinite(self.gain) or not math.isfinite(self.offset):
            raise ValueError('Source gain and offset must be finite')
        if not isinstance(self.output_unit, str):
            raise ValueError('Output unit must be text')

    def apply(self, samples):
        values = np.asarray(samples, dtype=float)
        if self.gain == 1. and self.offset == 0.:
            return values
        with np.errstate(over='raise', invalid='raise'):
            try:
                return values * self.gain + self.offset
            except FloatingPointError as exc:
                raise ValueError('Source conversion produced nonfinite values') from exc

    def units(self, source_units):
        unit = self.output_unit.strip()
        return [unit] * len(source_units) if unit else list(source_units)

    def metadata(self):
        return asdict(self)
