"""Channel selection helpers shared by GUI, LSL receiver and calibration."""


def channel_labels(info):
    """Return channel labels in LSL source order, filling absent labels."""
    count = info.channel_count()
    channel = info.desc().child('channels').child('channel')
    labels = []
    for i in range(count):
        labels.append((channel.child_value('label') or channel.child_value('name') or '').strip()
                      or f'Ch{i+1} (unlabeled)')
        channel = channel.next_sibling()
    return labels


def validated_indices(indices, count, kind):
    """Preserve source ordering; EEG multi-select, EDA/PPG exactly one."""
    chosen = list(indices)
    if not chosen:
        raise ValueError(f'Select at least one {kind} channel')
    if len(chosen) != len(set(chosen)) or any(
        not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= count
        for i in chosen
    ):
        raise ValueError(f'Invalid or duplicate {kind} channel index')
    if kind in ('EDA', 'PPG') and len(chosen) != 1:
        raise ValueError(f'{kind} requires exactly one selected channel')
    if kind not in ('EEG', 'EDA', 'PPG'):
        raise ValueError(f'Unsupported modality {kind}')
    return sorted(chosen)


def select_chunk(samples, indices):
    """Convert one LSL chunk to the selected columns."""
    import numpy as np
    x = np.asarray(samples, dtype=float)
    if x.ndim != 2:
        raise ValueError('LSL samples must be a 2D array')
    return x[:, indices]


def full_channel_labels(info, timeout=2.0):
    """Fetch expanded LSL stream metadata via inlet.info(), not resolve_streams().

    Stream resolution returns abbreviated StreamInfo with no description.
    Only the expanded info() response carries electrode/channel labels.
    Returns labels and an explanation if the publisher has no names.
    """
    from pylsl import StreamInlet
    inlet = StreamInlet(info, max_buflen=1)
    try:
        full = inlet.info(timeout=timeout)
        labels = channel_labels(full)
        unlabeled = [i for i, name in enumerate(labels) if name.endswith('(unlabeled)')]
        return labels, (
            f'{len(unlabeled)} of {len(labels)} channels have no LSL label/name '
            'in the publisher metadata.' if unlabeled else ''
        )
    finally:
        inlet.close_stream()
