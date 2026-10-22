"""Display-only voltage conversion; acquisition and processing keep source units."""
VOLTAGE_TO_UV = {'v': 1e6, 'volt': 1e6, 'volts': 1e6,
                 'mv': 1e3, 'millivolts': 1e3,
                 'uv': 1., 'microvolts': 1., 'microvolt': 1.,
                 'nv': 1e-3, 'nanovolts': 1e-3}
DEFAULT_EEG_DISPLAY_STEP = 20.
ARBITRARY_UNIT = 'a.u.'


def source_display_unit(units):
    """Compact source labels without changing sample values or inventing units."""
    aliases = {
        'v': 'V', 'volt': 'V', 'volts': 'V',
        'mv': 'mV', 'millivolt': 'mV', 'millivolts': 'mV',
        'uv': 'µV', 'microvolt': 'µV', 'microvolts': 'µV',
        'nv': 'nV', 'nanovolt': 'nV', 'nanovolts': 'nV',
        'us': 'µS', 'microsiemens': 'µS',
        'ms': 'mS', 'millisiemens': 'mS', 'siemens': 'S',
        'au': ARBITRARY_UNIT, 'a.u.': ARBITRARY_UNIT,
        'arbitrary units': ARBITRARY_UNIT,
        '': ARBITRARY_UNIT, 'n/a': ARBITRARY_UNIT, 'unknown': ARBITRARY_UNIT,
    }
    labels = []
    for unit in units:
        text = str(unit or '').strip()
        key = text.lower().replace('µ', 'u').replace('μ', 'u')
        labels.append(aliases.get(key, text))
    return labels[0] if labels and len(set(labels)) == 1 else ARBITRARY_UNIT


def eeg_display_scale(units, step=DEFAULT_EEG_DISPLAY_STEP):
    keys = [str(unit).strip().lower().replace('µ', 'u').replace('μ', 'u')
            for unit in units]
    if keys and all(key in VOLTAGE_TO_UV for key in keys):
        return tuple(step / VOLTAGE_TO_UV[key] for key in keys), 'µV'
    # Missing/unsupported metadata cannot justify a physical voltage label.
    return tuple(step for _ in keys), source_display_unit(units)


def stream_channel_units(info, indices):
    channel = info.desc().child('channels').child('channel')
    units = []
    for _ in range(info.channel_count()):
        units.append(channel.child_value('unit') or '')
        channel = channel.next_sibling()
    return [units[i] for i in indices]
