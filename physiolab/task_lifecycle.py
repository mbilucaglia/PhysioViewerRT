"""GUI-owned task lifetimes and modal presentation, without blocking joins."""
from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QProgressDialog


class OperationCancelled(RuntimeError):
    pass


class GenerationResultHandler(QObject):
    """Give a scoped callback explicit GUI affinity and QObject lifetime."""
    def __init__(self, callback, parent):
        super().__init__(parent)
        self.callback = callback

    @Slot(object, object, object)
    def receive(self, generation, result, error):
        self.callback(generation, result, error)


class TaskLifecycle(QObject):
    """Retain each QThread until its finished notification reaches the GUI."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tasks = set()
        self.closing = False

    def track(self, task):
        if self.closing:
            raise OperationCancelled('Application is closing')
        self.tasks.add(task)
        task.finished.connect(self._finished)

    @Slot()
    def _finished(self):
        task = self.sender()
        self.tasks.discard(task)
        task.deleteLater()

    def begin_close(self):
        self.closing = True
        for task in tuple(self.tasks):
            stop = getattr(task, 'request_stop', None)
            if stop is not None:
                stop()

    @property
    def idle(self):
        return not self.tasks


class TaskProgress(QProgressDialog):
    """Explicit GUI receiver for task results; completion closes on finished."""
    def __init__(self, text, parent):
        super().__init__(text, '', 0, 0, parent)
        self.outcome = None
        self.setCancelButton(None)

    @Slot(object, object)
    def receive(self, result, error):
        self.outcome = (result, error)

    @Slot()
    def finish_task(self):
        self.accept()
