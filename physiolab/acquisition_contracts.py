"""Named acquisition payload; retains the receiver's seven-item tuple API."""
from dataclasses import dataclass
from typing import ClassVar

import numpy as np


@dataclass(frozen=True)
class AcquisitionChunk:
    raw: np.ndarray
    filtered: np.ndarray
    names: list[str]
    metric: dict | None
    fs: float
    timestamps: np.ndarray
    acquired_at: float
    motion_cleaned: np.ndarray | None = None

    # Keep the original seven-item iteration/indexing contract. Optional
    # calibration payloads are named fields and never change legacy unpacking.
    _fields: ClassVar[tuple] = ('raw', 'filtered', 'names', 'metric', 'fs',
                                'timestamps', 'acquired_at')

    def __iter__(self):
        return iter(tuple(getattr(self, name) for name in self._fields))

    def __len__(self):
        return len(self._fields)

    def __getitem__(self, index):
        return tuple(self)[index]
