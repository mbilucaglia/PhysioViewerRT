"""Background LSL control-plane operations.

Discovery and expanded StreamInfo metadata may block for seconds. Their QThread
runners must never touch Qt widgets, and GUI callbacks never wait for them.
"""
from PySide6.QtCore import QThread, Signal

from .worker import discover
from .channel_selection import full_channel_labels, channel_labels


class LSLTask(QThread):
    completed = Signal(object, object, object)  # token, result, error

    def __init__(self, token, operation, info=None, parent=None):
        super().__init__(parent)
        self.token, self.operation, self.info = token, operation, info

    def run(self):
        try:
            if self.operation == 'discover':
                result = discover()
            elif self.operation == 'metadata':
                try:
                    result = full_channel_labels(self.info, timeout=2.0)
                except Exception as exc:
                    result = (channel_labels(self.info),
                              f'Unable to fetch full LSL channel metadata: {exc}')
            else:
                raise ValueError(f'Unknown LSL task: {self.operation}')
            self.completed.emit(self.token, result, None)
        except Exception as exc:
            self.completed.emit(self.token, None, str(exc))
