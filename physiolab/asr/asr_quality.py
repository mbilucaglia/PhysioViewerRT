"""Descriptive ASR training measures; not a performance or confidence score."""


def training_report(model):
    recorded = model.baseline_seconds
    retained = model.clean_seconds
    excluded = max(0., recorded - retained)
    minimum_status = 'met' if retained >= model.settings.minimum_baseline_seconds else 'not met'
    return {
        'recorded': f'{recorded:.1f} s',
        'retained': f'{retained:.1f} s ({100 * retained / recorded:.1f}%)',
        'excluded': f'{excluded:.1f} s ({100 * excluded / recorded:.1f}%)',
        'minimum': f'{model.settings.minimum_baseline_seconds:g} s required — {minimum_status}',
        'channels': f'{len(model.channels)} channels · {model.fs:g} Hz',
        'threshold': f'{model.settings.cutoff:g} σ',
    }
