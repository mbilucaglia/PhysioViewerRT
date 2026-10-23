"""State icons from the same SVG files referenced by Qt Designer."""
from pathlib import Path
# Load QtSvg so Windows can resolve the SVG icon plugin's Qt6Svg dependency.
from PySide6 import QtSvg
from PySide6.QtGui import QIcon

ICON_DIRECTORY = Path(__file__).resolve().parent.parent / 'assets' / 'icons'


def action_icon(name):
    return QIcon(str(ICON_DIRECTORY / (name + '.svg')))


def set_action(button, text, icon):
    button.setText(text)
    button.setIcon(action_icon(icon))
