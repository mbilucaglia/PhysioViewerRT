"""Display-only amplitude fitting; channel ratios and source data stay intact."""
import numpy as np
from .render_policy import RAW_DISPLAY_POLICY


def visible_gain(frame, seconds, show_raw=True, show_filtered=True, head=None):
    """One common gain fits extrema about every displayed channel baseline."""
    times, raw, filtered = frame[:3]
    times = np.asarray(times)
    if not len(times) or seconds <= 0:
        return None
    end = float(times[-1]) if head is None else float(head)
    keep = (times >= end-seconds) & (times <= end)
    offsets = RAW_DISPLAY_POLICY.offsets(raw.shape[1])
    peak = 0.
    for values, enabled in ((raw, show_raw), (filtered, show_filtered)):
        if enabled:
            deviations = np.abs(np.asarray(values)[keep]-offsets)
            finite = deviations[np.isfinite(deviations)]
            if len(finite):
                peak = max(peak, float(np.max(finite)))
    return RAW_DISPLAY_POLICY.fit_limit / peak if peak > 1e-12 else None
