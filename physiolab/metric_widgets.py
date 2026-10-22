"""Build scalable Qt metric controls from the presentation catalog."""
from PySide6.QtWidgets import QWidget, QCheckBox, QGridLayout, QVBoxLayout, QLabel


def build_metric_toggles(root, layout, definitions, callback, columns=6):
    host = QWidget()
    grid = QGridLayout(host)
    grid.setContentsMargins(0, 0, 0, 0)
    toggles = {}
    # Reuse Designer controls so stylesheet selectors and keyboard order survive.
    existing = root.findChildren(QCheckBox)
    for checkbox in existing:
        if checkbox.objectName().startswith('metricToggle'):
            layout.removeWidget(checkbox)
            checkbox.hide()
    for index, definition in enumerate(definitions):
        checkbox = root.findChild(QCheckBox, f'metricToggle{definition.name}')
        if checkbox is None or checkbox in toggles.values():
            checkbox = QCheckBox(definition.name)
        checkbox.setText(f'{definition.modality} · {definition.name}')
        checkbox.setToolTip(definition.description)
        checkbox.setChecked(True)
        grid.addWidget(checkbox, index // columns, index % columns)
        checkbox.show()
        checkbox.toggled.connect(callback)
        toggles[definition.key] = checkbox
    layout.insertWidget(0, host, 1)
    return toggles


def build_metric_readouts(host, definitions, columns=4):
    layout = QGridLayout(host)
    groups = {'EEG': ['IAF']}
    for definition in definitions:
        groups.setdefault(definition.modality, []).append(definition.name)
    labels, statuses = {}, {}
    for row, (kind, names) in enumerate(groups.items()):
        group = QVBoxLayout()
        group.addWidget(QLabel(f'<b>{kind} metrics</b>'))
        for name in names:
            label = QLabel(f'{name}: —')
            labels[kind, name] = label
            group.addWidget(label)
        status = QLabel('Waiting for stream / valid window')
        status.setWordWrap(True)
        statuses[kind] = status
        group.addWidget(status)
        layout.addLayout(group, row // columns, row % columns)
    return labels, statuses
