"""Wrap related controls as intact groups, using Qt size hints and DPI scaling."""
from PySide6.QtCore import QRect, QSize, Qt, QObject, QEvent
from PySide6.QtWidgets import QLayout, QWidget, QBoxLayout


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QRect(0, 0, width, 0), False)

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def sizeHint(self):
        width = sum(i.sizeHint().width() + self.spacing() for i in self.items)
        return QSize(width, self.heightForWidth(width))

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, True)

    def arrange(self, rect, apply):
        x, y, row_height = rect.x(), rect.y(), 0
        for item in self.items:
            if item.isEmpty():
                continue
            width = min(item.sizeHint().width(), rect.width())
            height = item.heightForWidth(width) if item.hasHeightForWidth() else item.sizeHint().height()
            if x > rect.x() and x + width > rect.x() + rect.width():
                x, y, row_height = rect.x(), y + row_height + self.spacing(), 0
            if apply:
                item.setGeometry(QRect(x, y, width, height))
            x += width + self.spacing()
            row_height = max(row_height, height)
        return y + row_height - rect.y()


def install_flow(host):
    old = host.layout()
    if isinstance(old, FlowLayout):
        return old
    spacing = old.spacing()
    widgets = []
    while old.count():
        item = old.takeAt(0)
        if item.widget() is not None:
            widgets.append(item.widget())
    # Transfer ownership before installing the adaptive layout on the same host.
    retired = QWidget()
    retired.setLayout(old)
    flow = FlowLayout(host, spacing=spacing if spacing >= 0 else 8)
    for widget in widgets:
        flow.addWidget(widget)
    retired.deleteLater()
    return flow


def install_designer_flows(root):
    for host in root.findChildren(QWidget):
        if host.property('wrapControls'):
            install_flow(host)


class AdaptiveCardRow(QObject):
    """Stack the Affect cards using viewport width, before content can overflow."""
    def __init__(self, viewport, layout):
        super().__init__(viewport)
        self.viewport, self.layout = viewport, layout
        viewport.installEventFilter(self)
        self.reflow()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.reflow()
        return super().eventFilter(watched, event)

    def reflow(self):
        required = sum(self.layout.itemAt(i).minimumSize().width()
                       for i in range(self.layout.count())) + 64
        direction = (QBoxLayout.Direction.TopToBottom if self.viewport.width() < required
                     else QBoxLayout.Direction.LeftToRight)
        if direction != self.layout.direction():
            self.layout.setDirection(direction)
