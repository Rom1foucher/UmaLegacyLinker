from __future__ import annotations

import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from ui_qt.core import OperationCancelled


class WorkerSignals(QObject):
    progress = Signal(int, str)
    log = Signal(str)
    result = Signal(object)
    error = Signal(str, str)
    cancelled = Signal()
    finished = Signal()


class FunctionWorker(QRunnable):
    """Run a backend operation without blocking Qt's event loop.

    The logger and progress callbacks double as cooperative cancellation
    checkpoints. Backends call them often, so a requested cancellation stops
    at the next step without any engine change.
    """

    def __init__(self, function: Callable[..., Any]):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()
        self.cancel_event = threading.Event()
        self.setAutoDelete(True)

    def _checkpoint(self) -> None:
        if self.cancel_event.is_set():
            raise OperationCancelled("Tâche annulée par l'utilisateur.")

    @Slot()
    def run(self) -> None:
        def log(message: str) -> None:
            self._checkpoint()
            self.signals.log.emit(message)

        def progress(value: int, message: str) -> None:
            self._checkpoint()
            self.signals.progress.emit(value, message)

        try:
            result = self.function(logger=log, progress=progress)
        except OperationCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:  # backend exceptions are presented by the UI
            self.signals.error.emit(str(exc), traceback.format_exc())
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()
