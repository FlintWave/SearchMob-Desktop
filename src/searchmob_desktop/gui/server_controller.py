"""`LocalServerController` runs the SearchMob HTTP server on a `QThread`.

uvicorn's `Server.run()` blocks, so it cannot live on the GUI thread. We move it to a dedicated
`QThread`, then ask it to stop by flipping `Server.should_exit = True`, which is the supported
shutdown path. The thread joins once `run()` returns.

The engine list and the suggestions provider are built the same way `cli.serve` builds them so
the served metasearch matches the CLI exactly. The vault is left locked in the GUI default (the
in-memory history store is used until the user explicitly enables encrypted storage).
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal

from searchmob_desktop.data.history import InMemoryHistoryStore
from searchmob_desktop.data.ranking_store import load_ranking_rules
from searchmob_desktop.engines import (
    EngineContext,
    EngineFn,
    SearchResult,
    fetch_brave_api,
    fetch_duckduckgo,
    fetch_marginalia,
    fetch_mojeek,
    fetch_mojeek_api,
    fetch_mwmbl,
    fetch_wikipedia,
    make_privacy_client,
)
from searchmob_desktop.gui.engines_catalog import ENGINE_CATALOG, is_engine_enabled
from searchmob_desktop.prefs import JsonPreferencesStore, UserPreferences
from searchmob_desktop.server import LOOPBACK_HOST, build_app
from searchmob_desktop.suggest import (
    CompositeSuggestionsProvider,
    HistorySuggestionsProvider,
    UpstreamSuggestionsProvider,
)

if TYPE_CHECKING:
    import httpx

_BRAVE_KEY_ENV = "SEARCHMOB_BRAVE_API_KEY"
_MOJEEK_KEY_ENV = "SEARCHMOB_MOJEEK_API_KEY"


def build_engines_from_prefs(prefs: UserPreferences) -> list[EngineFn]:
    """Compose the engines list using the prefs `engine_enabled` map plus environment keys.

    Free engines are filtered by the prefs map (default-on; absent entry = on). BYO-key engines
    are filtered both by the env var (no key, no request) and by the prefs map.
    """
    by_id: dict[str, EngineFn] = {
        "duckduckgo": fetch_duckduckgo,
        "wikipedia": fetch_wikipedia,
        "mojeek": fetch_mojeek,
        "marginalia": fetch_marginalia,
        "mwmbl": fetch_mwmbl,
    }
    enabled = dict(prefs.engine_enabled) if prefs.engine_enabled else {}
    engines: list[EngineFn] = []
    for entry in ENGINE_CATALOG:
        if entry.requires_api_key:
            continue
        if not is_engine_enabled(entry.id, enabled):
            continue
        fn = by_id.get(entry.id)
        if fn is not None:
            engines.append(fn)

    brave_key = os.environ.get(_BRAVE_KEY_ENV)
    if brave_key and is_engine_enabled("brave", enabled):

        async def _brave(client: httpx.AsyncClient, ctx: EngineContext) -> list[SearchResult]:
            return await fetch_brave_api(client, ctx, api_key=brave_key)

        engines.append(_brave)

    mojeek_key = os.environ.get(_MOJEEK_KEY_ENV)
    if mojeek_key and is_engine_enabled("mojeek-api", enabled):

        async def _mojeek_api(client: httpx.AsyncClient, ctx: EngineContext) -> list[SearchResult]:
            return await fetch_mojeek_api(client, ctx, api_key=mojeek_key)

        engines.append(_mojeek_api)
    return engines


class _UvicornWorker(QThread):
    """`QThread` that owns one uvicorn `Server` instance and shuts it down on request."""

    started_ok = Signal(int)
    failed = Signal(str)
    stopped = Signal()

    def __init__(
        self,
        engines: Sequence[EngineFn],
        host: str,
        port: int,
        prefs_store: JsonPreferencesStore,
        history_store: InMemoryHistoryStore,
    ) -> None:
        super().__init__()
        self._engines = engines
        self._host = host
        self._port = port
        self._prefs_store = prefs_store
        self._history_store = history_store
        self._server: object | None = None  # uvicorn.Server, deferred import
        self._ready = threading.Event()

    def run(self) -> None:
        # Defer the uvicorn import: it pulls a fair bit of code and we do not need it on systems
        # that never start the server.
        import uvicorn

        def _upstream_enabled() -> bool:
            try:
                return self._prefs_store.load().upstream_suggestions_enabled
            except OSError:
                return False

        composite = CompositeSuggestionsProvider(
            history=HistorySuggestionsProvider(self._history_store),
            upstream=UpstreamSuggestionsProvider(lambda: make_privacy_client(2.0)),
            upstream_enabled=_upstream_enabled,
        )

        app = build_app(
            self._engines,
            bound_port_getter=lambda: self._port,
            bound_host_getter=lambda: self._host,
            suggestions_provider=composite,
            ranking_rules=load_ranking_rules(),
        )
        config = uvicorn.Config(
            app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        self._server = server
        try:
            self.started_ok.emit(self._port)
            self._ready.set()
            # uvicorn.Server.run() builds its own asyncio loop and blocks until should_exit.
            server.run()
        except OSError as exc:
            self.failed.emit(f"server failed to bind: {exc}")
            self._ready.set()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            self._ready.set()
            return
        finally:
            self.stopped.emit()

    def request_stop(self) -> None:
        """Ask the uvicorn server to exit. Safe to call from the GUI thread."""
        server = self._server
        if server is None:
            return
        # uvicorn.Server.should_exit is a plain bool flag the run loop checks on its next tick.
        # Setting it from another thread is the documented shutdown path.
        try:
            server.should_exit = True  # type: ignore[attr-defined]
        except Exception:
            return


class LocalServerController(QObject):
    """Owns the server thread and exposes start/stop with Qt signals."""

    serverStarted = Signal(int)
    serverStopped = Signal()
    serverError = Signal(str)

    def __init__(
        self,
        prefs_store: JsonPreferencesStore,
        history_store: InMemoryHistoryStore | None = None,
        host: str = LOOPBACK_HOST,
        port: int = 8787,
    ) -> None:
        super().__init__()
        self._prefs_store = prefs_store
        self._history_store = history_store or InMemoryHistoryStore()
        self._host = host
        self._port = port
        self._worker: _UvicornWorker | None = None

    @property
    def is_running(self) -> bool:
        worker = self._worker
        return worker is not None and worker.isRunning()

    @property
    def bound_url(self) -> str | None:
        return f"http://{self._host}:{self._port}/" if self.is_running else None

    def set_host(self, host: str) -> None:
        """Update the bind host. Takes effect on the next `start()`; never restarts implicitly."""
        self._host = host

    def set_port(self, port: int) -> None:
        self._port = port

    def start(self) -> None:
        """Spin up the server thread. No-op if already running."""
        if self.is_running:
            return
        prefs = self._prefs_store.load()
        # Mirror the prefs history-enabled flag into the in-memory store the server hands to the
        # suggestions provider; flipping the toggle later requires a restart, which matches the
        # CLI's current behavior.
        self._history_store.set_enabled(prefs.history_enabled)
        engines = build_engines_from_prefs(prefs)
        worker = _UvicornWorker(
            engines=engines,
            host=self._host,
            port=self._port,
            prefs_store=self._prefs_store,
            history_store=self._history_store,
        )
        worker.started_ok.connect(self.serverStarted)
        worker.failed.connect(self.serverError)
        worker.stopped.connect(self.serverStopped)
        worker.finished.connect(self._on_thread_finished)
        self._worker = worker
        worker.start()

    def stop(self) -> None:
        """Ask the server to exit and wait briefly for the thread to join."""
        worker = self._worker
        if worker is None:
            return
        worker.request_stop()
        # Give uvicorn up to two seconds to drain. If it does not, drop the thread reference; the
        # OS will reclaim the socket once the process exits. We deliberately do not call
        # `QThread.terminate` (it is unsafe per Qt docs).
        worker.wait(2000)

    def _on_thread_finished(self) -> None:
        # Clear the worker reference once Qt confirms the thread is done so a subsequent start()
        # produces a fresh thread.
        self._worker = None


# Re-export an asyncio-side helper so callers in the GUI thread can run a one-shot async fn
# off the event loop. This is intentionally NOT used inside `_UvicornWorker.run` (uvicorn owns
# its own loop there); it is here so dialogs that need to run an aiohttp call once can do so.
def run_async(coro_factory) -> object:  # type: ignore[no-untyped-def]
    """`asyncio.run` shim for use in `BlockingWorker(lambda: run_async(...))` callers."""
    return asyncio.run(coro_factory())
