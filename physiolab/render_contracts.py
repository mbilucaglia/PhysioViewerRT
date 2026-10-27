"""Typed, immutable contracts between GUI snapshotting and raw preparation.

The NumPy chunk arrays referenced here are treated as immutable after intake.
No Qt or VisPy objects cross this boundary.
"""
from dataclasses import dataclass
from typing import Optional, Tuple, Protocol
from types import MappingProxyType
import numpy as np
from .render_policy import RAW_DISPLAY_POLICY


@dataclass(frozen=True)
class PreparedFrame:
    """Owned, read-only display arrays; timestamps are relative to session origin.

    Source samples remain in history. Values here include the named affine
    transform (centers, scales, shared channel offsets), before user gain.
    """
    times: np.ndarray
    raw: np.ndarray
    filtered: np.ndarray
    centers: np.ndarray
    scales: np.ndarray
    names: tuple
    connect: Optional[np.ndarray] = None  # Edge ending at each sample; no gap joins.

    # Numerical callers from before the refactor can still inspect the six
    # array fields. Runtime consumers use names; lifecycle metadata is never
    # inferred from positional entries.
    def __iter__(self):
        return iter((self.times,self.raw,self.filtered,self.centers,self.scales,self.names))

    def __getitem__(self,index):
        return tuple(self)[index]


@dataclass(frozen=True)
class ViewSpec:
    source_generation: int
    view_generation: int
    left: float
    right: float
    duration: float
    channels: int
    unit: str = 'a.u.'
    gain: float = 1.
    show_raw: bool = True
    show_filtered: bool = True


class RawBackend(Protocol):
    """The complete drawing boundary. All methods run on the GUI thread."""
    def present(self, frame: Optional[PreparedFrame], view: ViewSpec, fs: float) -> bool: ...
    def reset(self) -> None: ...
    def invalidate_history(self) -> None: ...
    def history_needs_replay(self, count: int, duration: float) -> bool: ...
    def close(self) -> None: ...


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
    source_generation: int = 0
    coverage: str = 'full'
    unit: str = 'a.u.'
    available_at: Optional[float] = None
    command: Optional[str] = None
    max_points: int = RAW_DISPLAY_POLICY.max_points


@dataclass(frozen=True)
class RawFrameRequest:
    ticket: int
    version: int
    sources: dict
    queued_at: float
    presentation_head: Optional[float] = None
    presentation_heads: Optional[dict] = None

    def __post_init__(self):
        object.__setattr__(self, 'sources', MappingProxyType(dict(self.sources)))
        object.__setattr__(self, 'presentation_heads', MappingProxyType(dict(self.presentation_heads or {})))


@dataclass(frozen=True)
class RawFrameResult:
    ticket: int
    version: int
    frames: dict
    prepare_ms: float = 0.
    queued_at: Optional[float] = None
    ready_at: Optional[float] = None
    presentation_head: Optional[float] = None
    presentation_heads: Optional[dict] = None
    outcomes: Optional[dict] = None
    sources: Optional[dict] = None
    started_at: Optional[float] = None

    def __post_init__(self):
        for name in ('frames', 'presentation_heads', 'outcomes', 'sources'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self,name) or {})))


@dataclass(frozen=True)
class FrameOutcome:
    status: str  # ready / no_data / failed / cancelled
    error: Optional[str] = None


class PreparationCancelled(Exception):
    pass
