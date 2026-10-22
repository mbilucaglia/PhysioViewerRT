"""Pure RAW viewport snapshot selection.

Only references to immutable chunks are returned. No Qt, GUI state,
NumPy copying or data reduction occurs on the caller's thread.
"""
from .render_contracts import RawSourceRequest


def build_raw_source(chunks, *, left, right, origin, reference=None,
                     vispy=False, latest=None, sweep_seconds=5.,
                     max_channels=8):
    """Select intersecting chunks and define the worker's viewport.

    The GPU path starts from a short live tail on a fresh sweep and
    subsequently submits only samples newer than the renderer's latest
    accepted sample. All data reduction remains in RawRenderWorker.
    """
    if not chunks or origin is None or right <= left:
        return None
    if vispy:
        if latest is not None and reference is not None:
            left = max(left, latest - .1)
        else:
            left = max(left, right - .35)
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
        decimation_span=(2. * sweep_seconds if vispy else None),
        max_channels=max_channels,
    )
