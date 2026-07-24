from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    progress = Signal(int, str)
    log = Signal(str)
    result = Signal(object)
    error = Signal(str, str)
    finished = Signal()


class FunctionWorker(QRunnable):
    """Run a backend operation without blocking Qt's event loop."""

    def __init__(self, function: Callable[..., Any]):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = self.function(
                logger=self.signals.log.emit,
                progress=self.signals.progress.emit,
            )
        except Exception as exc:  # backend exceptions are presented by the UI
            self.signals.error.emit(str(exc), traceback.format_exc())
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()

