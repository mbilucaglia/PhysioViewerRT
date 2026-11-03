"""Shared Move menus for existing splitter panels and wrapping metric cards."""
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMenu, QToolButton, QSplitter


class PanelArrangement(QObject):
    changed = Signal(object)

    def __init__(self, parent, container, panels, buttons, labels):
        super().__init__(parent)
        self.container, self.panels, self.labels = container, panels, labels
        self.default = self.order = tuple(panels)
        self.menus = {}
        for key, button in buttons.items():
            menu = QMenu(button)
            button.setMenu(menu)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu.aboutToShow.connect(lambda k=key:self.populate(k))
            self.menus[key] = menu

    def populate(self, key):
        menu = self.menus[key]
        menu.clear()
        for other in self.order:
            if other != key:
                action = menu.addAction(f'Swap with {self.labels[other]}')
                action.triggered.connect(lambda checked=False,a=key,b=other:self.swap(a,b))
        menu.addSeparator()
        menu.addAction('Restore default layout').triggered.connect(lambda:self.set_order(self.default))

    def swap(self, first, second):
        order = list(self.order)
        a,b = order.index(first),order.index(second)
        order[a],order[b] = order[b],order[a]
        self.set_order(order)

    def set_order(self, order):
        order = tuple(order)
        if len(order) != len(self.default) or set(order) != set(self.default):
            raise ValueError('Arrangement must include each panel exactly once')
        if order != self.order:
            if isinstance(self.container, QSplitter):
                sizes = self.container.sizes()
                for index,key in enumerate(order):
                    self.container.insertWidget(index,self.panels[key])
                self.container.setSizes(sizes)
            else:
                for panel in self.panels.values():
                    self.container.removeWidget(panel)
                for key in order:
                    self.container.addWidget(self.panels[key])
                self.container.invalidate()
                self.container.parentWidget().updateGeometry()
            self.order = order
        self.changed.emit(order)
