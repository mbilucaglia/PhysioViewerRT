"""Application icon and BrainLab organization branding."""
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


ASSETS = Path(__file__).resolve().parent.parent / 'assets'
LAB_LOGO_PATH = ASSETS / 'brainlab-logo.png'
APP_ICON_PATH = ASSETS / 'physioviewer.ico'


def apply_window_branding(window):
    icon = QIcon(str(APP_ICON_PATH))
    window.setWindowIcon(icon)
    app = QApplication.instance()
    app.setWindowIcon(icon)
    app.setApplicationName('PhysioViewerRT')
    app.setOrganizationName('BrainLab - Università IULM')
