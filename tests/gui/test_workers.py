"""Worker lifetime: a started worker must survive until its signal is delivered.

Regression for the "app vanishes on Check for updates" crash: the worker is a QRunnable whose
`signals` QObject was only held by a local variable at the call site. Once that went out of scope,
Python could GC the worker while the pool thread was still running, and the cross-thread `emit`
landed in a freed object - a segfault, made near-certain by rapid clicks. `start()` now parks the
worker in a module set until it finishes, so dropping the local reference (and a GC) is safe.

These are the only tests that pump the event system, so they take care not to disturb (or be
disturbed by) widgets/timers other GUI tests left behind: `removePostedEvents` clears stale queued
deliveries up front, and `sendPostedEvents` delivers our worker's signal *without* firing any
leftover timers/animations (which is what `processEvents` would do, and what crashed here).
"""

from __future__ import annotations

import gc

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QThreadPool

from searchmob_desktop.gui.workers import AsyncWorker, _inflight


@pytest.fixture(autouse=True)
def _isolate(qapp: object):  # type: ignore[no-untyped-def]
    QCoreApplication.removePostedEvents(None)
    yield
    # Workers retained past delivery (their deferred release is a zero-timer we never pump) would
    # leak into later tests; drop them once the pool is idle.
    QThreadPool.globalInstance().waitForDone(2000)
    _inflight.clear()
    QCoreApplication.removePostedEvents(None)


def _deliver() -> None:
    # Dispatch posted meta-call events (our queued `finished`/`failed` signals) only - no timers.
    QCoreApplication.sendPostedEvents(None, 0)


def test_started_worker_survives_dropped_ref_then_delivers(qapp: object) -> None:
    pool = QThreadPool.globalInstance()
    results: list[object] = []

    async def _coro() -> int:
        return 42

    worker: AsyncWorker[int] = AsyncWorker(_coro)
    worker.signals.finished.connect(results.append)
    worker.start(pool)
    del worker  # drop the only call-site reference, like the real handler does
    gc.collect()

    pool.waitForDone(5000)
    # The worker ran to completion without being collected mid-flight (the crash); it is still
    # retained because its result has not been delivered yet.
    assert len(_inflight) >= 1
    _deliver()
    assert results == [42]  # the call-site slot was delivered, not swallowed


def test_rapid_workers_all_deliver_without_crash(qapp: object) -> None:
    pool = QThreadPool.globalInstance()
    done: list[object] = []

    async def _coro() -> int:
        return 1

    # Mimic rapid clicking: many short-lived workers, local refs dropped, GC forced mid-flight.
    for _ in range(25):
        w: AsyncWorker[int] = AsyncWorker(_coro)
        w.signals.finished.connect(done.append)
        w.start(pool)
    gc.collect()

    pool.waitForDone(5000)
    _deliver()
    assert len(done) == 25


def test_failed_worker_delivers_error(qapp: object) -> None:
    pool = QThreadPool.globalInstance()
    errors: list[str] = []

    async def _boom() -> int:
        raise RuntimeError("nope")

    worker: AsyncWorker[int] = AsyncWorker(_boom)
    worker.signals.failed.connect(errors.append)
    worker.start(pool)
    del worker
    gc.collect()

    pool.waitForDone(5000)
    _deliver()
    assert errors and "nope" in errors[0]
