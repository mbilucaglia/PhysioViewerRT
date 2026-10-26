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
    return 'on', 'ASR ON', ('ASR has successfully processed fresh EEG chunks after filtering. '
        'ASR affects filtered/processed traces; Raw remains original input. '
        'This confirms execution, not artifact removal effectiveness. Model: '
        + worker.eeg_asr_model.model_id)
