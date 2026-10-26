"""Reusable desktop widgets without acquisition or application session state."""
import time
from PySide6.QtCore import QTimer, Qt, Signal, QObject, QEvent
from PySide6.QtWidgets import QToolButton, QMenu, QDialog, QVBoxLayout, QLabel, QPushButton, QCheckBox, QWidgetAction, QScrollArea, QWidget, QGridLayout
from .calibration import DURATION_SECONDS


class ChannelCheckBox(QCheckBox):
    """Make the whole channel row clickable, including space after its label."""

    def hitButton(self, position):
        return self.rect().contains(position)


class CheckChannelDropdown(QToolButton):
    """Checkbox popup: EEG multiple, EDA/PPG exactly one."""
    selection_changed = Signal()

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.names = []
        self.actions = []
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setFixedWidth(210)
        self.setToolTip('Choose channels; source labels are shown in the checklist')
        self.menu = QMenu(self)
        self.setMenu(self.menu)
        self.set_channels([])

    def set_channels(self, names):
        self.names = list(names)
        self.actions = []
        self.menu.clear()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 4, 8, 4)
        for index, name in enumerate(self.names):
            checkbox = ChannelCheckBox(f'{index + 1}: {name}')
            checkbox.setChecked(self.kind == 'EEG' or index == 0)
            checkbox.clicked.connect(lambda checked, i=index: self.select(i, checked))
            layout.addWidget(checkbox)
            self.actions.append(checkbox)
        if not self.names:
            layout.addWidget(QLabel('No channels available'))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setMinimumWidth(250)
        scroll.setFixedHeight(min(320, content.sizeHint().height() + 6))
        entry = QWidgetAction(self.menu)
        entry.setDefaultWidget(scroll)
        self.menu.addAction(entry)
        self.update_label()

    def select(self, index, checked):
        if self.kind in ('EDA', 'PPG'):
            for i, action in enumerate(self.actions):
                action.setChecked(i == index)
        else:
            self.actions[index].setChecked(checked)
        self.update_label()
        self.selection_changed.emit()

    def selected_indices(self):
        return [i for i, action in enumerate(self.actions) if action.isChecked()]

    def update_label(self):
        chosen = self.selected_indices()
        if not chosen:
            self.setText('Select channels')
            self.setToolTip('No channels selected. Open the dropdown to choose.')
            return
        selected = [f'{i + 1}: {self.names[i]}' for i in chosen]
        # Show the actual labels instead of just "N channels". Width is
        # bounded; the tooltip gives the unabridged list on hover.
        full = ', '.join(selected)
        self.setText(self.fontMetrics().elidedText(
            full, Qt.TextElideMode.ElideRight, self.width() - 30
        ))
        self.setToolTip('Selected source channels:\n' + '\n'.join(selected))


class ResponsiveSources(QObject):
    """Reflow the Designer grid into one column when its cards need more room."""

    def __init__(self, scroll):
        super().__init__(scroll)
        self.scroll = scroll
        self.grid = scroll.findChild(QGridLayout, 'sourcesLayout')
        self.entries = [(self.grid.itemAt(i).widget(), self.grid.getItemPosition(i))
                        for i in range(self.grid.count())]
        self.compact = None
        scroll.viewport().installEventFilter(self)
        self.reflow()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.reflow()
        return super().eventFilter(watched, event)

    def reflow(self):
        cards = [widget for widget, (_, _, _, span) in self.entries if span == 1]
        required = 2 * max(widget.minimumSizeHint().width() for widget in cards) + 64
        compact = self.scroll.viewport().width() < required
        if compact == self.compact:
            return
        self.compact = compact
        for widget, _ in self.entries:
            self.grid.removeWidget(widget)
        for row in range(7):
            self.grid.setRowStretch(row, 0)
        self.grid.setColumnStretch(1, 0 if compact else 1)
        for index, (widget, position) in enumerate(self.entries):
            self.grid.addWidget(widget, index, 0, 1, 1) if compact else self.grid.addWidget(widget, *position)
        self.grid.setRowStretch(len(self.entries) if compact else 4, 1)


class CalibrationScreen(QDialog):
    """Fullscreen 60-second calibration prompt. Esc cancels recording."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.started_at = None
        self.setWindowTitle(f'{kind} calibration')
        self.setStyleSheet('background: black; color: white;')
        # Native movable and maximizable window, initially over app plots.
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinMaxButtonsHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(900, 580)
        if parent is not None:
            rect = parent.frameGeometry()
            self.move(rect.center() - self.rect().center())
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.instruction = QLabel('Close your eyes' if kind == 'EYC' else 'Look at the dot')
        self.instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.instruction.setStyleSheet('font-size: 52px; color: white;')
        layout.addWidget(self.instruction)
        if kind == 'BSL':
            self.fixation = QLabel('•')
            self.fixation.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.fixation.setStyleSheet('font-size: 80px; color: white;')
            layout.addWidget(self.fixation)
        self.clock = QLabel('')
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock.setStyleSheet('font-size: 22px; color: #aaa;')
        layout.addWidget(self.clock)
        cancel = QPushButton('Cancel (Esc)')
        cancel.setFixedWidth(160)
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignCenter)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)

    def showEvent(self, event):
        super().showEvent(event)
        self.started_at = time.monotonic()
        self.timer.start()

    def tick(self):
        remaining = max(0, DURATION_SECONDS - (time.monotonic() - self.started_at))
        self.clock.setText(f'{remaining:.0f} s remaining')
        if remaining <= 0:
            self.timer.stop()
            self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.timer.stop()
            self.reject()
        else:
            super().keyPressEvent(event)
