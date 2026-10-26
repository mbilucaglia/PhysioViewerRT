"""Build scalable Qt metric controls from the presentation catalog."""
from PySide6.QtWidgets import QWidget, QCheckBox, QGridLayout, QVBoxLayout, QLabel, QFrame, QHBoxLayout, QToolButton
from PySide6.QtCore import Qt
from .panel_arrangement import PanelArrangement
from .ui_icons import action_icon
from PySide6.QtGui import QColor, QIcon, QPixmap
from .metric_catalog import metric_color
from .modality_labels import modality_label
from .flow_layout import install_flow


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
        checkbox.setText(f'{modality_label(definition.modality)} · {definition.name}')
        checkbox.setProperty('metricSelector', True)
        swatch = QPixmap(10, 10)
        swatch.fill(QColor(metric_color(index)))
        checkbox.setIcon(QIcon(swatch))
        checkbox.setToolTip(definition.description)
        checkbox.setChecked(True)
        grid.addWidget(checkbox, index // columns, index % columns)
        checkbox.show()
        checkbox.toggled.connect(callback)
        toggles[definition.key] = checkbox
    install_flow(host)
    layout.insertWidget(0, host, 1)
    return toggles


def build_metric_readouts(host, definitions, columns=4):
    layout = host.layout() or QGridLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    groups = {'EEG': ['IAF']}
    for definition in definitions:
        groups.setdefault(definition.modality, []).append(definition.name)
    labels, statuses = {}, {}
    cards, move_buttons, titles = {}, {}, {}
    for row, (kind, names) in enumerate(groups.items()):
        card = host.findChild(QFrame, f'{kind}MetricCard')
        if card is None:
            card = QFrame()
            card.setObjectName(f'{kind}MetricCard')
            card.setProperty('metricCard', True)
            group = QVBoxLayout(card)
            group.setContentsMargins(12, 12, 12, 12)
            group.addWidget(QLabel(f'{modality_label(kind)} metrics'))
        else:
            group = card.layout()
            placeholder = card.findChild(QLabel, f'{kind}MetricPlaceholder')
            if placeholder is not None:
                group.removeWidget(placeholder)
                placeholder.hide()
        first = group.itemAt(0)
        heading = first.widget() if first.widget() is not None else first.layout().itemAt(0).widget()
        heading.setProperty('metricHeading', True)
        button = card.findChild(QToolButton, kind+'MetricMove')
        if button is None:
            group.removeWidget(heading)
            header = QHBoxLayout()
            header.addWidget(heading)
            button = QToolButton()
            button.setText('Move')
            button.setIcon(action_icon('move'))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            header.addWidget(button)
            group.insertLayout(0, header)
        cards[kind], move_buttons[kind], titles[kind] = card, button, heading.text()
        for name in names:
            label = QLabel(f'{name}: —')
            label.setProperty('metricValue' if name != 'IAF' else 'metricStatus', True)
            labels[kind, name] = label
            group.addWidget(label)
        status = QLabel('Waiting for stream / valid window')
        status.setProperty('metricStatus', True)
        status.setWordWrap(True)
        statuses[kind] = status
        group.addWidget(status)
        layout.addWidget(card, row // columns, row % columns)
        layout.setColumnStretch(row % columns, 1)
    flow = install_flow(host)
    host.arrangement = PanelArrangement(host, flow, cards, move_buttons, titles)
    return labels, statuses
