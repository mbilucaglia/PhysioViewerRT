"""BrainLab assets shared by the window icon and Designer header."""
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


LAB_LOGO_PATH = Path(__file__).resolve().parent.parent / 'assets' / 'brainlab-logo.png'


def apply_window_branding(window):
    icon = QIcon(str(LAB_LOGO_PATH))
    window.setWindowIcon(icon)
    app = QApplication.instance()
    app.setWindowIcon(icon)
    app.setApplicationName('PhysioViewerRT')
    app.setOrganizationName('BrainLab - Università IULM')
