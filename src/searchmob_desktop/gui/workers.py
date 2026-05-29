"""QRunnable workers so the GUI thread never blocks on a network call or a vault unwrap.

`AsyncWorker` wraps an `async` callable in an `asyncio.run`, hands the result (or the exception)
back through the bundled `_WorkerSignals` QObject. `BlockingWorker` does the same for a plain
sync callable. Both call sites stay on the GUI thread: connect to the `finished` / `failed`
signals before submitting via `worker.start(pool)`.

Lifetime: a `QRunnable` handed to `QThreadPool` is owned and auto-deleted on the C++ side, but the
Python wrapper (and its `signals` QObject) is only kept alive by whatever references it. If the call
site drops its local reference - the usual pattern - Python can garbage-collect the wrapper while
the pool thread is still running, and the cross-thread `emit` then lands in a freed `signals`
object, crashing the process (seen as the app vanishing on a "Check for updates" click, especially
rapid clicks that pile up short-lived workers). `start()` therefore parks the worker in a
module-level set until its signal fires, so it cannot be collected mid-run.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

# Workers that have been started but whose result/error has not yet been delivered. Mutated only on
# the GUI thread (in `start()` and in the GUI-thread `finished`/`failed` slots), so no lock needed.
_inflight: set[_BaseWorker] = set()


class _WorkerSignals(QObject):
    """Signal carrier for a worker. QRunnable cannot emit signals itself."""

    finished = Signal(object)
    failed = Signal(str)


class _BaseWorker(QRunnable):
    """Shared lifetime handling: own a `signals` carrier and stay alive until it fires."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = _WorkerSignals()
        # Drop the self-reference once the outcome has been delivered (both run on the GUI thread).
        self.signals.finished.connect(self._release)
        self.signals.failed.connect(self._release)

    def start(self, pool: QThreadPool) -> None:
        """Retain self against GC, then submit to the pool. Use this instead of `pool.start()`."""
        _inflight.add(self)
        pool.start(self)

    def _release(self, *_args: object) -> None:
        # Defer to the next GUI event-loop turn so the call site's own `finished`/`failed` slot
        # (delivered as a sibling of this one) has run before we drop the last reference. Releasing
        # immediately could collect the `signals` object mid-dispatch and swallow that slot.
        QTimer.singleShot(0, lambda: _inflight.discard(self))


class AsyncWorker[T](_BaseWorker):
    """Run an async coroutine on the thread pool, emit the result on the GUI thread.

    Construct with a zero-arg factory that returns a fresh coroutine each call, NOT a coroutine
    object: `asyncio.run` can only consume a coroutine once, and re-running this `QRunnable`
    would double-await the same coroutine. The factory keeps the contract single-use-friendly.
    """

    def __init__(self, coro_factory: Callable[[], Coroutine[Any, Any, T]]) -> None:
        super().__init__()
        self._coro_factory = coro_factory

    def run(self) -> None:
        try:
            result: T = asyncio.run(self._coro_factory())
        except Exception as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)


class BlockingWorker[T](_BaseWorker):
    """Run a plain blocking callable on the thread pool, emit the result on the GUI thread."""

    def __init__(self, fn: Callable[[], T]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            result: T = self._fn()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)
