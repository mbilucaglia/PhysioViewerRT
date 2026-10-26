"""Wrap related controls as intact groups, using Qt size hints and DPI scaling."""
from PySide6.QtCore import QRect, QSize, Qt, QObject, QEvent
from PySide6.QtWidgets import QLayout, QWidget, QBoxLayout, QVBoxLayout


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


class ViewportPageLayout(QVBoxLayout):
    """Report the height needed by controls, allowing plots to use remaining room.

    QScrollArea otherwise treats a VBox's preferred plot height as mandatory
    whenever any toolbar implements height-for-width.
    """
    def heightForWidth(self, width):
        return minimum_layout_height(self, width)

    def minimumHeightForWidth(self, width):
        return self.heightForWidth(width)


def fit_scroll_page(scroll):
    host = scroll.widget()
    old = host.layout()
    margins, spacing, name = old.contentsMargins(), old.spacing(), old.objectName()
    entries = [(old.itemAt(i), old.stretch(i)) for i in range(old.count())]
    while old.count():
        old.takeAt(0)
    retired = QWidget()
    retired.setLayout(old)
    layout = ViewportPageLayout(host)
    layout.setObjectName(name)
    layout.setContentsMargins(margins)
    layout.setSpacing(spacing)
    for index, (item, stretch) in enumerate(entries):
        layout.addItem(item)
        layout.setStretch(index, stretch)
    retired.deleteLater()


def minimum_item_height(item, width):
    widget = item.widget()
    layout = widget.layout() if widget is not None else item.layout()
    if isinstance(layout, QBoxLayout):
        height = minimum_layout_height(layout, width)
    else:
        height = item.heightForWidth(width) if item.hasHeightForWidth() else item.minimumSize().height()
    return max(item.minimumSize().height(), height)


def minimum_layout_height(layout, width):
    margins = layout.contentsMargins()
    width = max(0, width - margins.left() - margins.right())
    items = [(layout.itemAt(i), layout.stretch(i)) for i in range(layout.count())
             if not layout.itemAt(i).isEmpty()]
    gaps = max(0, len(items) - 1) * max(0, layout.spacing())
    if layout.direction() in (QBoxLayout.Direction.LeftToRight, QBoxLayout.Direction.RightToLeft):
        minimum_widths = [item.minimumSize().width() for item, _ in items]
        extra = max(0, width - sum(minimum_widths) - gaps)
        weights = [stretch or 1 for _, stretch in items]
        heights = [minimum_item_height(item, minimum + int(extra * weight / sum(weights)))
                   for (item, _), minimum, weight in zip(items, minimum_widths, weights)]
        height = max(heights, default=0)
    else:
        height = sum(minimum_item_height(item, width) for item, _ in items) + gaps
    return margins.top() + margins.bottom() + height
