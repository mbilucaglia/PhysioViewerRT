"""Named acquisition payload; retains the receiver's seven-item tuple API."""
from typing import NamedTuple

import numpy as np


class AcquisitionChunk(NamedTuple):
    raw: np.ndarray
    filtered: np.ndarray
    names: list[str]
    metric: dict | None
    fs: float
    timestamps: np.ndarray
    acquired_at: float
