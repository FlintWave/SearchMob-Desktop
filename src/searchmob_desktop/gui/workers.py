"""QRunnable workers so the GUI thread never blocks on a network call or a vault unwrap.

`AsyncWorker` wraps an `async` callable in an `asyncio.run`, hands the result (or the exception)
back through the bundled `_WorkerSignals` QObject. `BlockingWorker` does the same for a plain
sync callable. Both call sites stay on the GUI thread: connect to the `finished` / `failed`
signals before submitting to `QThreadPool`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal


class _WorkerSignals(QObject):
    """Signal carrier for a worker. QRunnable cannot emit signals itself."""

    finished = Signal(object)
    failed = Signal(str)


class AsyncWorker[T](QRunnable):
    """Run an async coroutine on the thread pool, emit the result on the GUI thread.

    Construct with a zero-arg factory that returns a fresh coroutine each call, NOT a coroutine
    object: `asyncio.run` can only consume a coroutine once, and re-running this `QRunnable`
    would double-await the same coroutine. The factory keeps the contract single-use-friendly.
    """

    def __init__(self, coro_factory: Callable[[], Coroutine[Any, Any, T]]) -> None:
        super().__init__()
        self._coro_factory = coro_factory
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            result: T = asyncio.run(self._coro_factory())
        except Exception as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)


class BlockingWorker[T](QRunnable):
    """Run a plain blocking callable on the thread pool, emit the result on the GUI thread."""

    def __init__(self, fn: Callable[[], T]) -> None:
        super().__init__()
        self._fn = fn
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            result: T = self._fn()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)
