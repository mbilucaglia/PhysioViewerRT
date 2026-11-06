"""Display names independent of acquisition identifiers and saved file keys."""

MODALITY_LABELS = {'EEG': 'EEG', 'PPG': 'PPG', 'EDA': 'SC', 'EI': 'EI', 'TOPO': 'EEG topoplot'}


def modality_label(kind):
    return MODALITY_LABELS.get(kind, kind)
