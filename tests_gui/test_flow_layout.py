"""Control groups wrap without losing their actions or overlapping each other."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QGridLayout
from physiolab.flow_layout import install_flow


class FlowLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_resize_wraps_groups_without_overlap_or_losing_connections(self):
        host = QWidget()
        grid = QGridLayout(host)
        clicked = []
        buttons = []
        for index in range(3):
            button = QPushButton(str(index))
            button.setFixedSize(100, 32)
            button.clicked.connect(lambda checked=False, i=index:clicked.append(i))
            grid.addWidget(button, 0, index)
            buttons.append(button)
        flow = install_flow(host)
        host.show()
        try:
            for width in (340, 150, 250, 340):
                height = flow.heightForWidth(width)
                flow.setGeometry(QRect(0, 0, width, height))
                for i, button in enumerate(buttons):
                    self.assertGreaterEqual(button.x(), 0)
                    self.assertLessEqual(button.geometry().right(), width)
                    self.assertLessEqual(button.geometry().bottom(), height)
                    for other in buttons[:i]:
                        self.assertFalse(button.geometry().intersects(other.geometry()))
                if width == 150:
                    self.assertEqual(len({b.y() for b in buttons}), 3)
                if width == 340:
                    self.assertEqual(len({b.y() for b in buttons}), 1)
            for button in buttons:
                button.click()
            self.assertEqual(clicked, [0, 1, 2])
            self.assertIs(install_flow(host), flow)
        finally:
            host.close()
            host.deleteLater()
            self.app.processEvents()


    def test_plot_preferred_height_does_not_force_scrolling_when_it_can_fit(self):
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QScrollArea, QVBoxLayout
        from physiolab.flow_layout import fit_scroll_page

        class Plot(QWidget):
            def sizeHint(self):
                return QSize(400, 1200)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        outer = QVBoxLayout(host)
        toolbar = QWidget()
        grid = QGridLayout(toolbar)
        button = QPushButton('View')
        grid.addWidget(button, 0, 0)
        install_flow(toolbar)
        outer.addWidget(toolbar)
        plot = Plot()
        plot.setMinimumHeight(100)
        outer.addWidget(plot, 1)
        scroll.setWidget(host)
        fit_scroll_page(scroll)
        scroll.show()
        try:
            for height in (600, 80, 600):
                scroll.resize(800, height)
                self.app.processEvents()
                if height == 600:
                    self.assertEqual(scroll.verticalScrollBar().maximum(), 0)
                    self.assertEqual(host.height(), scroll.viewport().height())
                else:
                    self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        finally:
            scroll.close()
            scroll.deleteLater()
            self.app.processEvents()


    def test_raw_workspace_switches_orientation_without_replacing_panels(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QSplitter
        from physiolab.flow_layout import AdaptiveRawWorkspace
        viewport = QWidget()
        splitter = QSplitter(Qt.Orientation.Vertical)
        panels = [QWidget(), QWidget()]
        for panel in panels:
            panel.setMinimumWidth(200)
            splitter.addWidget(panel)
        controller = AdaptiveRawWorkspace(viewport, splitter)
        viewport.show()
        try:
            for width, expected in ((1600, Qt.Orientation.Horizontal),
                                    (800, Qt.Orientation.Vertical),
                                    (1600, Qt.Orientation.Horizontal)):
                viewport.resize(width, 800)
                self.app.processEvents()
                self.assertEqual(splitter.orientation(), expected)
                self.assertEqual([splitter.widget(i) for i in range(2)], panels)
        finally:
            viewport.close()
            splitter.close()
            viewport.deleteLater()
            splitter.deleteLater()
            self.app.processEvents()
