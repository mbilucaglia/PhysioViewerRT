"""Compatibility of baseline references, independent of workers and widgets."""
import numpy as np


def compatible_references(analysis, live_configurations, iaf_hz, *,
                          asr_enabled=False, replay_pending=False,
                          replay_error=None, tonic_configuration=None):
    references = dict(analysis.get('metrics', {}))
    configurations = analysis.get('source_configurations', {})
    # ACC baselines are valid when recorded with the same input cleaning.
    # Legacy baselines without provenance cannot establish that match.
    for kind, live in live_configurations.items():
        if (live and live.get('motion_reference')
                and configurations.get(kind, {}).get('motion_reference') != live['motion_reference']):
            references.pop(kind, None)
    for kind, baseline in configurations.items():
        live = live_configurations.get(kind)
        if live is not None and live != baseline:
            references.pop(kind, None)
    if (replay_pending or replay_error
            or not np.isclose(analysis.get('iaf_hz_used', iaf_hz), iaf_hz)
            or (asr_enabled and 'asr_model_id' not in configurations.get('EEG', {}))):
        references.pop('EEG', None)
    metadata = analysis.get('tonic_sc') or {}
    if not (metadata.get('configuration_id')
            and metadata['configuration_id'] == tonic_configuration):
        references.pop('EDA', None)
    if not (references.get('PPG', {}).get('HR') and references.get('EDA', {}).get('SCL')):
        references.pop('EI', None)
    return references
