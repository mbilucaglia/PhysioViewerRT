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


def set_panel_expanded(button, expanded):
    set_action(button, 'Restore' if expanded else 'Expand',
               'collapse' if expanded else 'expand')
    button.setToolTip('Restore the panel arrangement.' if expanded else
                      'Expand this panel to fill the workspace.')


def set_view_paused(button, paused):
    set_action(button, 'Play' if paused else 'Pause', 'play' if paused else 'pause')
    button.setToolTip('Resume the display; acquisition has continued.' if paused else
                      'Pause the display; acquisition and processing continue.')
