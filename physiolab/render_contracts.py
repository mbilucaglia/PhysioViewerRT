"""Typed, immutable contracts between GUI snapshotting and raw preparation.

The NumPy chunk arrays referenced here are treated as immutable after intake.
No Qt or VisPy objects cross this boundary.
"""
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class RawSourceRequest:
    chunks: tuple
    left: float
    right: float
    origin: float
    reference: Optional[Tuple[object, object]] = None
    decimation_span: Optional[float] = None
    max_channels: int = 8


@dataclass(frozen=True)
class RawFrameRequest:
    ticket: int
    version: int
    sources: dict
    queued_at: float
