"""Truthful acquisition feedback, independent of the requested checkbox state."""

def asr_runtime_state(worker, now, pending=False):
    if pending:
        return 'waiting', 'ASR updating…', 'Waiting for EEG processing reconfiguration.'
    if worker is None or not worker.active:
        return 'idle', 'ASR idle', 'Start an EEG stream to see its processing state.'
    status = worker.asr_status
    if 'bypassed' in status.lower():
        return 'bypassed', 'ASR BYPASSED', status
    if worker.eeg_asr_model is None:
        return 'off', 'ASR OFF', 'EEG is filtered without ASR.'
    last = worker.asr_last_processed_at
    if last is None or now-last > 2.:
        return 'waiting', 'ASR ON · waiting', 'ASR enabled; waiting for fresh successfully processed EEG samples.'
    correction = getattr(worker, 'asr_last_correction_at', None)
    detail = ('ASR continuously monitors filtered EEG. The LED lights only when '
        'the backend applies non-identity reconstruction, including release blending. '
        'A correction pulse stays visible for 0.5 s. Raw remains original input. '
        'Model: ' + worker.eeg_asr_model.model_id)
    if correction is not None and 0. <= now-correction <= .5:
        return 'correcting', 'ASR correcting', detail
    return 'monitoring', 'ASR monitoring', detail
