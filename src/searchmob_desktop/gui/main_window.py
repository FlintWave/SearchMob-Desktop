"""Main GUI shell. A `QMainWindow` with a top search bar, the results list, a small toolbar of
action buttons (Server, Browser setup, Settings, About), and a status bar that shows the bound
URL when the local server is running.

Search is async: pressing Enter (or the Search button) submits an `AsyncWorker` to
`QThreadPool`, which runs `asyncio.run(aggregate(...))` off the GUI thread. Results land back on
the GUI thread via the worker's `finished` signal.
"""

from __future__ import annotations

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from searchmob_desktop.data.history import InMemoryHistoryStore
from searchmob_desktop.engines import EngineContext, SearchResult, aggregate
from searchmob_desktop.gui.about_dialog import AboutDialog
from searchmob_desktop.gui.browser_setup_dialog import BrowserSetupDialog
from searchmob_desktop.gui.results_view import ResultsView
from searchmob_desktop.gui.server_controller import (
    LocalServerController,
    build_engines_from_prefs,
)
from searchmob_desktop.gui.settings_dialog import SettingsDialog
from searchmob_desktop.gui.theme import apply_theme
from searchmob_desktop.gui.workers import AsyncWorker
from searchmob_desktop.prefs import JsonPreferencesStore
from searchmob_desktop.server import LOOPBACK_HOST


class MainWindow(QMainWindow):
    """Top-level shell."""

    def __init__(
        self,
        prefs_store: JsonPreferencesStore | None = None,
        history_store: InMemoryHistoryStore | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("SearchMob Desktop")
        self.resize(960, 720)

        self._prefs_store = prefs_store or JsonPreferencesStore()
        self._history_store = history_store or InMemoryHistoryStore()
        self._history_store.set_enabled(self._prefs_store.load().history_enabled)
        self._server = LocalServerController(
            prefs_store=self._prefs_store,
            history_store=self._history_store,
            host=LOOPBACK_HOST,
            port=8787,
        )
        self._server.serverStarted.connect(self._on_server_started)
        self._server.serverStopped.connect(self._on_server_stopped)
        self._server.serverError.connect(self._on_server_error)

        self._pool = QThreadPool.globalInstance()

        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setSpacing(8)

        # Search bar row.
        search_row = QHBoxLayout()
        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("Search the web")
        self._query_input.returnPressed.connect(self._on_submit)
        self._search_btn = QPushButton("Search")
        self._search_btn.clicked.connect(self._on_submit)
        search_row.addWidget(self._query_input, stretch=1)
        search_row.addWidget(self._search_btn)
        outer.addLayout(search_row)

        # Status line above the results: idle / loading / empty / error / count.
        self._status_label = QLabel("Enter a query to search.")
        self._status_label.setProperty("role", "muted")
        outer.addWidget(self._status_label)

        # Results view.
        self._results = ResultsView()
        outer.addWidget(self._results, stretch=1)

        self.setCentralWidget(central)

        # Toolbar with the four primary actions.
        toolbar = QToolBar("Actions", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._toggle_server_action = QAction("Start server", self)
        self._toggle_server_action.triggered.connect(self._on_toggle_server)
        toolbar.addAction(self._toggle_server_action)

        browser_action = QAction("Browser setup", self)
        browser_action.triggered.connect(self._on_open_browser_setup)
        toolbar.addAction(browser_action)

        settings_action = QAction("Settings", self)
        settings_action.setShortcut(QKeySequence.StandardKey.Preferences)
        settings_action.triggered.connect(self._on_open_settings)
        toolbar.addAction(settings_action)

        about_action = QAction("About", self)
        about_action.triggered.connect(self._on_open_about)
        toolbar.addAction(about_action)

        # Status bar shows the bound URL while the server runs.
        status = QStatusBar(self)
        self.setStatusBar(status)
        status.showMessage("Server stopped.")

    # --- Search ------------------------------------------------------------------------------

    def _on_submit(self) -> None:
        query = self._query_input.text().strip()
        if not query:
            return
        self._status_label.setText("Searching ...")
        self._results.clear()
        self._search_btn.setEnabled(False)

        prefs = self._prefs_store.load()
        engines = build_engines_from_prefs(prefs)
        ctx = EngineContext(query=query, max_results=10, timeout_seconds=5.0)

        async def _run() -> list[SearchResult]:
            return await aggregate(ctx, engines)

        worker: AsyncWorker[list[SearchResult]] = AsyncWorker(_run)
        worker.signals.finished.connect(self._on_results_ready)
        worker.signals.failed.connect(self._on_search_failed)
        # Record the search in the (in-memory) history store if enabled. The store handles the
        # disabled-no-op case itself.
        try:
            self._history_store.add(query)
        except Exception:
            pass
        self._pool.start(worker)

    def _on_results_ready(self, results: object) -> None:
        self._search_btn.setEnabled(True)
        if not isinstance(results, list):
            self._status_label.setText("Search failed: unexpected result type.")
            return
        if not results:
            self._status_label.setText("No results found.")
            return
        self._status_label.setText(f"{len(results)} results.")
        self._results.set_results(results)

    def _on_search_failed(self, message: str) -> None:
        self._search_btn.setEnabled(True)
        self._status_label.setText(f"Search failed: {message}")

    # --- Server ------------------------------------------------------------------------------

    def _on_toggle_server(self) -> None:
        if self._server.is_running:
            self._server.stop()
        else:
            self._server.start()

    def _on_server_started(self, port: int) -> None:
        self._toggle_server_action.setText("Stop server")
        bound = self._server.bound_url or f"http://127.0.0.1:{port}/"
        self.statusBar().showMessage(f"Server running at {bound}")

    def _on_server_stopped(self) -> None:
        self._toggle_server_action.setText("Start server")
        self.statusBar().showMessage("Server stopped.")

    def _on_server_error(self, message: str) -> None:
        self._toggle_server_action.setText("Start server")
        self.statusBar().showMessage("Server error.")
        QMessageBox.warning(self, "Server error", message)

    # --- Dialogs -----------------------------------------------------------------------------

    def _on_open_settings(self) -> None:
        dialog = SettingsDialog(
            prefs_store=self._prefs_store,
            server_controller=self._server,
            history_store=self._history_store,
            parent=self,
        )

        def _on_theme_changed(theme: str) -> None:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                # `QApplication.instance()` returns `QCoreApplication`; cast for the type checker.
                apply_theme(app, theme)  # type: ignore[arg-type]

        dialog.themeChanged.connect(_on_theme_changed)
        dialog.exec()

    def _on_open_browser_setup(self) -> None:
        host = "127.0.0.1"
        port: int | None = 8787 if self._server.is_running else None
        BrowserSetupDialog(host=host, port=port, parent=self).exec()

    def _on_open_about(self) -> None:
        AboutDialog(self).exec()

    # --- Lifecycle ---------------------------------------------------------------------------

    def closeEvent(self, event):  # type: ignore[no-untyped-def]
        # Best-effort: stop the server thread so the process can exit cleanly. If uvicorn is
        # mid-request, the 2-second `wait()` in the controller's stop() is the upper bound.
        try:
            self._server.stop()
        except Exception:
            pass
        super().closeEvent(event)
