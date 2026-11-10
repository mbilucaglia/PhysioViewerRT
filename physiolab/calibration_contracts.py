"""Named results crossing the calibration I/O boundary."""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CalibrationSaved:
    path: str


@dataclass(frozen=True)
class CalibrationLoaded:
    metadata: dict[str, Any]
    streams: dict[str, Any]
