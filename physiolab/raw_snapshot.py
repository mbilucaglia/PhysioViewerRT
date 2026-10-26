"""Pure RAW viewport snapshot selection.

Only references to immutable chunks are returned. No Qt, GUI state,
NumPy copying or data reduction occurs on the caller's thread.
"""
from .render_contracts import RawSourceRequest
from .render_policy import RAW_DISPLAY_POLICY


def build_raw_source(chunks, *, left, right, origin, reference=None,
                     vispy=False, latest=None, replay_history=False, sweep_seconds=5.,
                     max_channels=RAW_DISPLAY_POLICY.max_single_channels, shared_scale=None, fit_traces=False, center_trace='raw'):
    """Select intersecting chunks and define the worker's viewport.

    The GPU path starts from a short live tail on a fresh sweep and
    subsequently submits only samples newer than the renderer's latest
    accepted sample. All data reduction remains in RawRenderWorker.
    """
    if not chunks or origin is None or right <= left:
        return None
    if vispy:
        if replay_history:
            pass  # Retain the requested two-cycle history for new GPU layers.
        elif latest is not None and reference is not None:
            left = max(left, latest - RAW_DISPLAY_POLICY.tail_overlap_seconds)
        else:
            left = max(left, right - RAW_DISPLAY_POLICY.initial_tail_seconds)
    lower, upper = origin + left, origin + right
    recent = []
    for chunk in reversed(chunks):
        stamps = chunk[0]
        if not len(stamps):
            continue
        if stamps[-1] < lower:
            break
        if stamps[0] <= upper:
            recent.append(chunk)
    if not recent:
        return None
    return RawSourceRequest(
        chunks=tuple(reversed(recent)),
        left=left, right=right, origin=origin,
        reference=reference,
        decimation_span=(RAW_DISPLAY_POLICY.history_cycles * sweep_seconds if vispy else None),
        max_channels=max_channels,
        shared_scale=shared_scale,
        fit_traces=fit_traces,
        center_trace=center_trace,
    )
