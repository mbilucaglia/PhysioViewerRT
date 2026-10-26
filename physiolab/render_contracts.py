"""Typed, immutable contracts between GUI snapshotting and raw preparation.

The NumPy chunk arrays referenced here are treated as immutable after intake.
No Qt or VisPy objects cross this boundary.
"""
from dataclasses import dataclass
from typing import Optional, Tuple
from .render_policy import RAW_DISPLAY_POLICY


@dataclass(frozen=True)
class RawSourceRequest:
    chunks: tuple
    left: float
    right: float
    origin: float
    reference: Optional[Tuple[object, object]] = None
    decimation_span: Optional[float] = None
    max_channels: int = RAW_DISPLAY_POLICY.max_single_channels
    shared_scale: object = None
    fit_traces: bool = False
    center_trace: str = 'raw'


@dataclass(frozen=True)
class RawFrameRequest:
    ticket: int
    version: int
    sources: dict
    queued_at: float
    presentation_head: Optional[float] = None


@dataclass(frozen=True)
class RawFrameResult:
    ticket: int
    version: int
    frames: dict
    prepare_ms: float = 0.
    queued_at: Optional[float] = None
    ready_at: Optional[float] = None
    presentation_head: Optional[float] = None
