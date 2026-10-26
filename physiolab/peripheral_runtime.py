"""Waveform modification feedback; deliberately not a signal-quality measure."""

def peripheral_runtime_state(worker, now, pending=False):
    if pending:
        return 'waiting','Reduction updating…','Waiting for processing reconfiguration.'
    if worker is None or not worker.active:
        return 'idle','Reduction idle','Start this stream to see its reduction state.'
    method = worker.preprocessing.get('artifact_reduction','off')
    if method == 'off':
        return 'off','Reduction OFF','Artifact reduction is off; ordinary filters are independent.'
    name = 'Hampel' if method == 'hampel' else 'Wavelet'
    last,changed,seconds,warming = getattr(worker,'reduction_feedback',(None,None,0.,True))
    if last is None or warming:
        progress = f' {min(seconds,8.):.1f}/8 s' if method == 'wavelet' else ''
        return 'waiting',name+' buffering'+progress,('Waiting for acquired samples: eight seconds for wavelet, '
            'seven samples initially for Hampel. Both raw and processed traces wait together.')
    detail = ('Green means emitted samples changed before ordinary filters (tolerance: '
        'rtol 1e-9, atol 1e-12); it does not establish artifact removal or signal quality. '
        'The pulse lasts 0.5 s and follows delivery, not the original artifact time. '
        'Wavelet operates on every window and may modify clean physiology continuously. '
        'Hampel replaces samples beyond three local median/MAD scales. '
        'Wavelet emits one-second batches after eight-second startup; Hampel waits three samples. '
        'Raw input remains unchanged. Display pause does not pause processing.')
    if now-last > 2.:
        return 'waiting',name+' waiting',detail+' No fresh processed samples in the last two seconds.'
    if changed is not None and 0. <= now-changed <= .5:
        return 'correcting',name+' modifying',detail
    return 'monitoring',name+' monitoring',detail
