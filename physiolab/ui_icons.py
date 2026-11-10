"""State icons from the same SVG files referenced by Qt Designer."""
from pathlib import Path
# Load QtSvg so Windows can resolve the SVG icon plugin's Qt6Svg dependency.
from PySide6 import QtSvg
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon

ICON_DIRECTORY = Path(__file__).resolve().parent.parent / 'assets' / 'icons'
ACTION_ICON_SIZE = QSize(22, 22)
ACTION_BUTTON_SIZE = QSize(32, 32)


def action_icon(name):
    return QIcon(str(ICON_DIRECTORY / (name + '.svg')))


def set_action(button, text, icon):
    button.setText(text)
    button.setIcon(action_icon(icon))
    if not text:
        button.setIconSize(ACTION_ICON_SIZE)
        button.setMinimumSize(ACTION_BUTTON_SIZE)
        # The application-wide QToolButton rule adds 11 px horizontal padding.
        # Icon-only controls are often fixed at 38 px, so that padding clips the SVG.
        button.setStyleSheet('QToolButton { padding: 0px; }')
        if hasattr(button, 'setToolButtonStyle'):
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)


def set_panel_expanded(button, expanded):
    action = 'Restore' if expanded else 'Expand'
    set_action(button, '', 'collapse' if expanded else 'expand')
    button.setAccessibleName(action)
    button.setToolTip('Restore the panel arrangement.' if expanded else
                      'Expand this panel to fill the workspace.')


def set_view_paused(button, paused):
    set_action(button, 'Play' if paused else 'Pause', 'play' if paused else 'pause')
    button.setToolTip('Resume the display; acquisition has continued.' if paused else
                      'Pause the display; acquisition and processing continue.')
