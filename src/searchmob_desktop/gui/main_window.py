"""Main GUI shell. A `QMainWindow` with a top search bar, the results list, a small toolbar of
action buttons (Server, Browser setup, Settings, About), and a status bar that shows the bound
URL when the local server is running.

Search is async: pressing Enter (or the Search button) submits an `AsyncWorker` to
`QThreadPool`, which runs `asyncio.run(aggregate(...))` off the GUI thread. Results land back on
the GUI thread via the worker's `finished` signal.
"""

from __future__ import annotations

from html import escape
from importlib.resources import as_file, files

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from searchmob_desktop.data.history import HistoryStore
from searchmob_desktop.data.history_factory import build_history_store
from searchmob_desktop.data.ranking_store import load_ranking_rules, save_ranking_rules
from searchmob_desktop.engines import EngineContext, SearchResult, aggregate
from searchmob_desktop.engines.correct import start_background_corrector
from searchmob_desktop.engines.rank import RankRule, apply_ranking, host_of_url
from searchmob_desktop.gui.about_dialog import AboutDialog
from searchmob_desktop.gui.browser_setup_dialog import BrowserSetupDialog
from searchmob_desktop.gui.history_dialog import HistoryDialog
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


def app_icon() -> QIcon:
    """The app launcher icon, loaded from the bundled resources (empty QIcon if unavailable)."""
    try:
        resource = files("searchmob_desktop.resources").joinpath("icon.png")
        with as_file(resource) as path:
            return QIcon(str(path))
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return QIcon()


class MainWindow(QMainWindow):
    """Top-level shell."""

    def __init__(
        self,
        prefs_store: JsonPreferencesStore | None = None,
        history_store: HistoryStore | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("SearchMob Desktop")
        self.setWindowIcon(app_icon())
        self.resize(980, 760)
        self.setMinimumSize(520, 420)
        # Set by the tray "Quit" action so closeEvent really exits instead of hiding to tray.
        self._really_quit = False
        self._tray_hint_shown = False

        self._prefs_store = prefs_store or JsonPreferencesStore()
        prefs = self._prefs_store.load()
        # Persistent encrypted history when enabled + vault available, else in-memory (per-session).
        self._history_store = history_store or build_history_store(prefs)
        self._history_store.set_enabled(prefs.history_enabled)
        # Result-ranking rules (block/lower/raise/pin, lenses, goggles), loaded once and applied to
        # every result list. `_raw_results` keeps the pre-ranking list so a rule change re-ranks
        # without re-searching.
        self._ranking_rules = load_ranking_rules()
        self._raw_results: list[SearchResult] = []
        # On-device "did you mean"; the dictionary loads off-thread so early searches just get no
        # suggestion. The last submitted query is kept so the result handler can offer a correction.
        self._corrector = start_background_corrector(
            history_terms=lambda: [e.query for e in self._history_store.recent(500)]
        )
        self._last_query = ""
        # Bind per the saved network-mode preference so a profile with network mode on listens on
        # the LAN from launch (the Settings toggle still rebinds on the next server restart).
        self._server = LocalServerController(
            prefs_store=self._prefs_store,
            history_store=self._history_store,
            host="0.0.0.0" if prefs.network_access_enabled else LOOPBACK_HOST,
            port=8787,
        )
        self._server.serverStarted.connect(self._on_server_started)
        self._server.serverStopped.connect(self._on_server_stopped)
        self._server.serverError.connect(self._on_server_error)

        self._pool = QThreadPool.globalInstance()

        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 16, 20, 12)
        outer.setSpacing(12)

        # Search bar row: a roomy field with a prominent accent-filled action button.
        search_row = QHBoxLayout()
        search_row.setSpacing(10)
        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("Search the web privately")
        self._query_input.setClearButtonEnabled(True)
        self._query_input.returnPressed.connect(self._on_submit)
        self._search_btn = QPushButton("Search")
        self._search_btn.setProperty("role", "primary")
        self._search_btn.setDefault(True)
        self._search_btn.setMinimumWidth(110)
        self._search_btn.clicked.connect(self._on_submit)
        search_row.addWidget(self._query_input, stretch=1)
        search_row.addWidget(self._search_btn)
        outer.addLayout(search_row)

        # Status line above the results: idle / loading / empty / error / count.
        self._status_label = QLabel("Enter a query to search.")
        self._status_label.setProperty("role", "muted")
        outer.addWidget(self._status_label)

        # "Did you mean: X" banner from the on-device corrector. Hidden until a search yields a
        # suggestion; clicking the link re-runs the search with the corrected query.
        self._didyoumean = QLabel()
        self._didyoumean.setObjectName("didyoumean")
        self._didyoumean.setTextFormat(Qt.TextFormat.RichText)
        self._didyoumean.setOpenExternalLinks(False)
        self._didyoumean.linkActivated.connect(self._on_didyoumean_clicked)
        self._didyoumean.hide()
        outer.addWidget(self._didyoumean)

        # Body swaps between a friendly empty state and the results list so the window never shows a
        # bare void before the first search.
        self._body = QStackedWidget()
        self._empty_state = self._build_empty_state()
        self._results = ResultsView()
        self._results.ruleRequested.connect(self._on_rule_requested)
        self._body.addWidget(self._empty_state)
        self._body.addWidget(self._results)
        self._body.setCurrentWidget(self._empty_state)
        outer.addWidget(self._body, stretch=1)

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

        history_action = QAction("History", self)
        history_action.triggered.connect(self._on_open_history)
        toolbar.addAction(history_action)

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

        # System tray: lets the app live in the tray/applet area instead of quitting on close.
        self._tray: QSystemTrayIcon | None = None
        self._setup_tray()

    # --- Empty state -------------------------------------------------------------------------

    def _build_empty_state(self) -> QWidget:
        """A centered placeholder shown before the first search and when a search finds nothing."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        icon = app_icon()
        if not icon.isNull():
            badge = QLabel()
            badge.setPixmap(icon.pixmap(72, 72))
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(badge)

        heading = QLabel("Search the web privately")
        heading.setProperty("role", "heading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        subtitle = QLabel(
            "Results are aggregated across engines on this device. Nothing is stored by default."
        )
        subtitle.setProperty("role", "muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        return widget

    # --- Tray --------------------------------------------------------------------------------

    def _setup_tray(self) -> None:
        """Create the tray icon and its menu, if the host OS exposes a system tray."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray = QSystemTrayIcon(app_icon(), self)
        tray.setToolTip("SearchMob Desktop")

        menu = QMenu(self)
        self._tray_show_action = QAction("Show window", self)
        self._tray_show_action.triggered.connect(self._show_from_tray)
        menu.addAction(self._tray_show_action)

        self._tray_server_action = QAction("Start server", self)
        self._tray_server_action.triggered.connect(self._on_toggle_server)
        menu.addAction(self._tray_server_action)

        menu.addSeparator()
        quit_action = QAction("Quit SearchMob", self)
        quit_action.triggered.connect(self._quit_from_tray)
        menu.addAction(quit_action)

        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray = tray

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # A left-click (Trigger) or double-click toggles the window's visibility.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._really_quit = True
        self.close()

    # --- Search ------------------------------------------------------------------------------

    def _on_submit(self) -> None:
        query = self._query_input.text().strip()
        if not query:
            return
        self._last_query = query
        self._status_label.setText("Searching ...")
        self._didyoumean.hide()
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
        worker.start(self._pool)

    def _on_results_ready(self, results: object) -> None:
        self._search_btn.setEnabled(True)
        if not isinstance(results, list):
            self._status_label.setText("Search failed: unexpected result type.")
            self._body.setCurrentWidget(self._empty_state)
            return
        if not results:
            self._raw_results = []
            self._status_label.setText("No results found.")
            self._body.setCurrentWidget(self._empty_state)
            self._maybe_show_correction()
            return
        self._raw_results = results
        self._body.setCurrentWidget(self._results)
        self._apply_ranking_and_show()
        self._maybe_show_correction()

    def _apply_ranking_and_show(self) -> None:
        """Re-rank the last raw results with the current rules and update the view + status."""
        ranked = apply_ranking(
            self._raw_results,
            self._ranking_rules,
            host_of=lambda r: host_of_url(r.url),
            text_of=lambda r: f"{r.title} {r.snippet}",
        )
        self._results.set_results(ranked)
        hidden = len(self._raw_results) - len(ranked)
        suffix = f" ({hidden} hidden by your rules)" if hidden > 0 else ""
        self._status_label.setText(f"{len(ranked)} results{suffix}.")

    def _on_rule_requested(self, domain: str, rule: RankRule) -> None:
        """A right-click ranking action on a result domain: persist it and re-rank in place."""
        if rule == RankRule.NORMAL:
            self._ranking_rules = self._ranking_rules.without_domain_rule(domain)
        else:
            self._ranking_rules = self._ranking_rules.with_domain_rule(domain, rule)
        save_ranking_rules(self._ranking_rules)
        if self._raw_results:
            self._apply_ranking_and_show()

    def _maybe_show_correction(self) -> None:
        """Offer a 'Did you mean: X' link when the on-device corrector suggests one."""
        suggestion = None
        try:
            suggestion = self._corrector.suggest(self._last_query)
        except Exception:
            suggestion = None
        if suggestion is None:
            self._didyoumean.hide()
            return
        corrected = escape(suggestion.corrected)
        self._didyoumean.setText(f'Did you mean: <a href="#correct">{corrected}</a>')
        self._didyoumean.show()

    def _on_didyoumean_clicked(self, _link: str) -> None:
        suggestion = None
        try:
            suggestion = self._corrector.suggest(self._last_query)
        except Exception:
            suggestion = None
        if suggestion is None:
            return
        self._query_input.setText(suggestion.corrected)
        self._on_submit()

    def _on_search_failed(self, message: str) -> None:
        self._search_btn.setEnabled(True)
        self._status_label.setText(f"Search failed: {message}")
        self._body.setCurrentWidget(self._empty_state)

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
        if self._tray is not None:
            self._tray_server_action.setText("Stop server")
            self._tray.setToolTip(f"SearchMob Desktop - {bound}")

    def _on_server_stopped(self) -> None:
        self._toggle_server_action.setText("Start server")
        self.statusBar().showMessage("Server stopped.")
        if self._tray is not None:
            self._tray_server_action.setText("Start server")
            self._tray.setToolTip("SearchMob Desktop")

    def _on_server_error(self, message: str) -> None:
        self._toggle_server_action.setText("Start server")
        self.statusBar().showMessage("Server error.")
        if self._tray is not None:
            self._tray_server_action.setText("Start server")
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

        def _on_rules_changed() -> None:
            # The ranking tab edited the vault-stored rules; reload and re-rank current results.
            self._ranking_rules = load_ranking_rules()
            if self._raw_results:
                self._apply_ranking_and_show()

        dialog.themeChanged.connect(_on_theme_changed)
        dialog.rulesChanged.connect(_on_rules_changed)
        dialog.exec()

    def _on_open_browser_setup(self) -> None:
        from searchmob_desktop.gui.browser_setup_dialog import choose_setup_host
        from searchmob_desktop.server import local_hostnames

        prefs = self._prefs_store.load()
        running = self._server.is_running
        port: int | None = 8787 if running else None
        host = choose_setup_host(
            network_enabled=prefs.network_access_enabled,
            configured_hostnames=prefs.network_hostnames,
            local_names=sorted(local_hostnames()),
        )
        # Network mode gates the query routes, so the setup URLs must carry the token.
        token = (
            prefs.network_access_token or None
            if (prefs.network_access_enabled and prefs.network_access_token)
            else None
        )
        BrowserSetupDialog(host=host, port=port, parent=self, token=token).exec()

    def _on_open_history(self) -> None:
        HistoryDialog(self._history_store, parent=self).exec()

    def _on_open_about(self) -> None:
        AboutDialog(self).exec()

    # --- Lifecycle ---------------------------------------------------------------------------

    def closeEvent(self, event):  # type: ignore[no-untyped-def]
        # When a tray is available, closing the window hides it to the tray instead of quitting,
        # so the local server keeps running and the app stays a click away. The tray's "Quit"
        # action sets `_really_quit` to perform a real shutdown.
        if self._tray is not None and not self._really_quit:
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self._tray.showMessage(
                    "SearchMob is still running",
                    "The app stays in the tray. Use the tray menu to quit.",
                    app_icon(),
                    4000,
                )
            return

        # Real shutdown. Best-effort: stop the server thread so the process can exit cleanly. If
        # uvicorn is mid-request, the 2-second wait() in the controller's stop() is the upper bound.
        try:
            self._server.stop()
        except Exception:
            pass
        if self._tray is not None:
            self._tray.hide()
        super().closeEvent(event)
