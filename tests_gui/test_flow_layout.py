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
