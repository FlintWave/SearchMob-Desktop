"""Main GUI shell. A `QMainWindow` with a top search bar, the results list, a small toolbar of
action buttons (Server, Browser setup, Settings, About), and a status bar that shows the bound
URL when the local server is running.

Search is async: pressing Enter (or the Search button) submits an `AsyncWorker` to
`QThreadPool`, which runs `asyncio.run(aggregate(...))` off the GUI thread. Results land back on
the GUI thread via the worker's `finished` signal.
"""

from __future__ import annotations

import asyncio
import sys
import time
from html import escape
from importlib.resources import as_file, files
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
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
from searchmob_desktop.data.personalization_store import (
    load_personalization,
    save_personalization,
)
from searchmob_desktop.data.ranking_store import load_ranking_rules, save_ranking_rules
from searchmob_desktop.engines import (
    DEFAULT_POOL_SIZE,
    AggregateOutcome,
    EngineContext,
    EngineOutcome,
    SearchResult,
    aggregate_with_status,
    make_privacy_client,
)
from searchmob_desktop.engines.correct import start_background_corrector
from searchmob_desktop.engines.local_llm import LlmConfig, stream_answer
from searchmob_desktop.engines.media_intent import (
    ActionsRow,
    MediaCategory,
    build_actions_row,
    detect_category,
    promote_media,
)
from searchmob_desktop.engines.query_operators import parse_query_operators
from searchmob_desktop.engines.rank import (
    PersonalizationModel,
    RankRule,
    apply_ranking,
    host_of_url,
    personalize_reorder,
)
from searchmob_desktop.engines.rank.personalize import query_terms, update_from_click
from searchmob_desktop.engines.rank.slop_blocklist import load_slop_domains
from searchmob_desktop.engines.sort import SortMode, sort_results
from searchmob_desktop.engines.verticals import Vertical, transform_query
from searchmob_desktop.engines.wiki_summary import SummaryBox, summary_for_query
from searchmob_desktop.gui.about_dialog import AboutDialog
from searchmob_desktop.gui.browser_setup_dialog import BrowserSetupDialog
from searchmob_desktop.gui.history_dialog import HistoryDialog
from searchmob_desktop.gui.language import language_bridge
from searchmob_desktop.gui.onboarding_dialog import ONBOARDING_VERSION
from searchmob_desktop.gui.results_view import ResultsView
from searchmob_desktop.gui.server_controller import (
    LocalServerController,
    build_engines_from_prefs,
)
from searchmob_desktop.gui.settings_dialog import SettingsDialog
from searchmob_desktop.gui.theme import DARK, active_theme, apply_theme
from searchmob_desktop.gui.workers import AsyncWorker
from searchmob_desktop.i18n import N_, tr, trc, trn
from searchmob_desktop.prefs import JsonPreferencesStore
from searchmob_desktop.server import LOOPBACK_HOST
from searchmob_desktop.update import (
    VersionTag,
    check_if_due,
    fetch_latest,
    reconcile_pending_update,
)
from searchmob_desktop.update_download import default_download_dir, download_and_verify
from searchmob_desktop.version import __version__


def app_icon() -> QIcon:
    """The app launcher icon, loaded from the bundled resources (empty QIcon if unavailable)."""
    try:
        resource = files("searchmob_desktop.resources").joinpath("icon.png")
        with as_file(resource) as path:
            return QIcon(str(path))
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return QIcon()


def _gui_row_label(category: MediaCategory) -> str:
    """The localized verb heading the media actions row. Literal `trc` calls for the extractor."""
    if category is MediaCategory.MUSIC:
        return trc("media actions", "Listen on")
    if category is MediaCategory.FILM_TV:
        return trc("media actions", "Watch on")
    if category is MediaCategory.BOOKS:
        return trc("media actions", "Read on")
    return trc("media actions", "Play on")


# How often, while the window stays open, to re-run the throttled update check. `check_if_due` keeps
# the ~daily throttle, so most ticks do no network at all; this only bounds HOW LONG after a release
# (published while the app was already running) the notification can lag. Without it the check ran
# once per launch, so a user who never relaunched was never told a new version existed.
_UPDATE_RECHECK_INTERVAL_MS = 60 * 60 * 1000


class MainWindow(QMainWindow):
    """Top-level shell."""

    # Marshal local-AI streaming updates from the worker thread to the GUI thread. The int is a
    # generation id so deltas from a superseded search are ignored once a newer search starts.
    _answer_delta = Signal(int, str)
    _answer_final = Signal(int, object)

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
        # Per-engine outcome for the last search (contributed / empty / failed), shown as an
        # unobtrusive "N of M engines responded" suffix on the status line. On-device only.
        self._engine_status: tuple[EngineOutcome, ...] = ()
        # Detected media category for the last search (from the summary entity), or None; drives the
        # bounded canonical-platform promotion in `_apply_ranking_and_show`.
        self._media_category: MediaCategory | None = None
        # The list currently shown (after sort + personalization + rules). Kept so a result click
        # can learn from its displayed position (the personalization skip-above signal).
        self._displayed_results: list[SearchResult] = []
        # Opt-in click personalization: a learned, bounded ranking boost. Loaded from the vault only
        # when enabled; an empty model is a harmless no-op when it is off.
        self._personalization_enabled = prefs.personalization_enabled
        self._personalization = (
            load_personalization() if prefs.personalization_enabled else PersonalizationModel()
        )
        # Result sort order ("fresh"/"date"/"relevance"); re-sorts in place without re-searching.
        self._sort_mode = SortMode.from_value(prefs.sort_mode)
        # Active search vertical (Web/News/Forums/Academic). Changing it re-runs the search because
        # the query sent to the engines is scoped differently per vertical.
        self._vertical = Vertical.WEB
        # On-device "did you mean"; the dictionary loads off-thread so early searches just get no
        # suggestion. The last submitted query is kept so the result handler can offer a correction.
        self._corrector = start_background_corrector(
            history_terms=lambda: [e.query for e in self._history_store.recent(500)]
        )
        self._last_query = ""
        # The operator-free text of the last query (see `query_operators`) and whether it carried
        # any operator syntax. The clean text drives sort/personalization/click training; the flag
        # skips the corrector, whose word-spelling logic would just mangle operators.
        self._last_clean_query = ""
        self._last_has_operators = False
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
        # Local-AI streaming state: a monotonically increasing id per answer request, and the text
        # accumulated so far for the current one. The signals deliver worker-thread updates here.
        self._answer_gen = 0
        self._answer_accum = ""
        self._answer_delta.connect(self._on_answer_delta)
        self._answer_final.connect(self._on_answer_final)

        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 16, 20, 12)
        outer.setSpacing(12)

        # "Update available" banner, pinned at the very top (hidden until a check finds a newer
        # release). Surfaced from persisted prefs on launch and from the background check below.
        self._pending_update: tuple[str, str] | None = None
        self._update_notified = False
        self._update_banner = self._build_update_banner()
        outer.addWidget(self._update_banner)

        # Search bar row: a roomy field with a prominent accent-filled action button.
        search_row = QHBoxLayout()
        search_row.setSpacing(10)
        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText(tr("Search the web privately"))
        self._query_input.setClearButtonEnabled(True)
        self._query_input.returnPressed.connect(self._on_submit)
        self._search_btn = QPushButton(tr("Search"))
        self._search_btn.setProperty("role", "primary")
        self._search_btn.setDefault(True)
        self._search_btn.setMinimumWidth(110)
        self._search_btn.clicked.connect(self._on_submit)
        search_row.addWidget(self._query_input, stretch=1)
        search_row.addWidget(self._search_btn)
        # Quick light/dark toggle on the homepage, mirroring the served page. Labels itself with the
        # theme it will switch to (a sun for Light, a moon for Dark).
        self._theme_btn = QPushButton()
        self._theme_btn.setProperty("role", "chip")
        self._theme_btn.setToolTip(tr("Switch between light and dark"))
        self._theme_btn.clicked.connect(self._on_toggle_theme)
        search_row.addWidget(self._theme_btn)
        self._update_theme_button()
        outer.addLayout(search_row)

        # Category tabs (Web/News/Forums/Academic). Each scopes the query over the same engines; no
        # new endpoint or API key. Switching re-runs the search because the engine query differs.
        vertical_row = QHBoxLayout()
        vertical_row.setSpacing(8)
        self._vertical_group = QButtonGroup(self)
        self._vertical_group.setExclusive(True)
        # Keep (button -> English label) so a language change can re-translate each chip in place.
        # Labels are N_-marked (with context) so the extractor finds them despite the loop variable.
        self._vertical_buttons: list[tuple[QPushButton, str]] = []
        for label, value in (
            (N_("Web", context="search category"), Vertical.WEB),
            (N_("News", context="search category"), Vertical.NEWS),
            (N_("Forums", context="search category"), Vertical.FORUMS),
            (N_("Academic", context="search category"), Vertical.ACADEMIC),
        ):
            btn = QPushButton(trc("search category", label))
            btn.setCheckable(True)
            btn.setProperty("role", "chip")
            btn.setChecked(value is Vertical.WEB)
            self._vertical_group.addButton(btn)
            btn.setProperty("vertical", value.value)
            vertical_row.addWidget(btn)
            self._vertical_buttons.append((btn, label))
        vertical_row.addStretch(1)
        self._vertical_group.buttonClicked.connect(self._on_vertical_clicked)
        outer.addLayout(vertical_row)

        # Status line + sort control above the results: idle / loading / empty / error / count.
        status_row = QHBoxLayout()
        # The idle status; kept as the "current" status string so a language change re-renders it.
        self._status_label = QLabel(tr("Enter a query to search."))
        self._status_label.setProperty("role", "muted")
        status_row.addWidget(self._status_label, stretch=1)
        # Scope (lens) selector: pick the active personalization lens, mirroring the served page's
        # scope bar. Hidden until at least one lens exists (created in Settings -> Result ranking).
        self._scope_label = QLabel(tr("Scope") + ":")
        self._scope_label.setProperty("role", "muted")
        status_row.addWidget(self._scope_label)
        self._scope_combo = QComboBox()
        self._scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        status_row.addWidget(self._scope_combo)
        self._sort_label = QLabel(tr("Sort") + ":")
        self._sort_label.setProperty("role", "muted")
        status_row.addWidget(self._sort_label)
        self._sort_combo = QComboBox()
        # (English label, mode) kept so a language change rebuilds the items, keeping the selection.
        # N_-marked (with context) so the extractor finds the labels despite the loop variable.
        self._sort_options: tuple[tuple[str, SortMode], ...] = (
            (N_("Freshest + Relevant", context="sort order"), SortMode.FRESH_RELEVANT),
            (N_("Date", context="sort order"), SortMode.DATE),
            (N_("Relevance", context="sort order"), SortMode.RELEVANCE),
        )
        for label, mode in self._sort_options:
            self._sort_combo.addItem(trc("sort order", label), mode.value)
        self._sort_combo.setCurrentIndex(max(0, self._sort_combo.findData(self._sort_mode.value)))
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        status_row.addWidget(self._sort_combo)
        outer.addLayout(status_row)
        # Populate the scope selector from the loaded rules (and toggle its visibility).
        self._refresh_scope_combo()

        # "Did you mean: X" banner from the on-device corrector. Hidden until a search yields a
        # suggestion; clicking the link re-runs the search with the corrected query.
        self._didyoumean = QLabel()
        self._didyoumean.setObjectName("didyoumean")
        self._didyoumean.setTextFormat(Qt.TextFormat.RichText)
        self._didyoumean.setOpenExternalLinks(False)
        self._didyoumean.linkActivated.connect(self._on_didyoumean_clicked)
        self._didyoumean.hide()
        outer.addWidget(self._didyoumean)

        # Optional local-AI answer card, populated after results when the feature is enabled and a
        # local model server is reachable. Hidden otherwise (and on any error).
        self._answer_card = self._build_answer_card()
        self._answer_card.hide()
        outer.addWidget(self._answer_card)

        # Contextual Wikipedia summary card, shown above the results for entity-like queries.
        self._summary_card = self._build_summary_card()
        self._summary_card.hide()
        outer.addWidget(self._summary_card)
        self._actions_card = self._build_actions_card()
        self._actions_card.hide()
        outer.addWidget(self._actions_card)

        # Body swaps between a friendly empty state and the results list so the window never shows a
        # bare void before the first search.
        self._body = QStackedWidget()
        self._empty_state = self._build_empty_state()
        self._results = ResultsView()
        self._results.ruleRequested.connect(self._on_rule_requested)
        self._results.resultActivated.connect(self._on_result_activated)
        self._body.addWidget(self._empty_state)
        self._body.addWidget(self._results)
        self._body.setCurrentWidget(self._empty_state)
        outer.addWidget(self._body, stretch=1)

        self.setCentralWidget(central)

        # Toolbar with the four primary actions.
        toolbar = QToolBar(tr("Actions"), self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # The toggle text reflects the server state; it is set by the started/stopped handlers (and
        # by _retranslate, which re-derives it from the current state).
        self._toggle_server_action = QAction(tr("Start server"), self)
        self._toggle_server_action.triggered.connect(self._on_toggle_server)
        toolbar.addAction(self._toggle_server_action)

        self._browser_action = QAction(tr("Browser setup"), self)
        self._browser_action.triggered.connect(self._on_open_browser_setup)
        toolbar.addAction(self._browser_action)

        self._history_action = QAction(tr("History"), self)
        self._history_action.triggered.connect(self._on_open_history)
        toolbar.addAction(self._history_action)

        self._settings_action = QAction(tr("Settings"), self)
        self._settings_action.setShortcut(QKeySequence.StandardKey.Preferences)
        self._settings_action.triggered.connect(self._on_open_settings)
        toolbar.addAction(self._settings_action)

        self._about_action = QAction(tr("About"), self)
        self._about_action.triggered.connect(self._on_open_about)
        toolbar.addAction(self._about_action)

        # Status bar shows the bound URL while the server runs.
        status = QStatusBar(self)
        self.setStatusBar(status)
        status.showMessage(tr("Server stopped."))

        # System tray: lets the app live in the tray/applet area instead of quitting on close.
        self._tray: QSystemTrayIcon | None = None
        self._setup_tray()

        # Re-translate the whole shell live when the UI language changes (from the Settings picker).
        language_bridge().languageChanged.connect(self._retranslate)

        # Setup wizard: shown on first run, and once more after an update that adds a step worth
        # seeing (when the saved onboarding revision is behind the app's current one).
        if not prefs.onboarding_completed or prefs.onboarding_version < ONBOARDING_VERSION:
            QTimer.singleShot(0, self._show_onboarding)

        # Surface a pending update found by an earlier check (persisted in prefs). A fresh throttled
        # check is kicked off on first show (see showEvent), so it only runs for a real launch.
        self._update_check_started = False
        self._surface_pending_update_from_prefs(prefs)

    def _show_onboarding(self) -> None:
        from searchmob_desktop.gui.onboarding_dialog import OnboardingDialog

        OnboardingDialog(
            prefs_store=self._prefs_store,
            server_controller=self._server,
            parent=self,
        ).exec()

    def _retranslate(self, _tag: str = "") -> None:
        """Re-apply translated text to the persistent shell after a UI-language change.

        Static chrome (search bar, category tabs, sort/scope controls, toolbar, tray, cards, empty
        state, update banner) updates live. Transient status messages keep their last text and
        re-render in the new language on the next search or server event.
        """
        self._query_input.setPlaceholderText(tr("Search the web privately"))
        self._search_btn.setText(tr("Search"))
        self._theme_btn.setToolTip(tr("Switch between light and dark"))
        self._update_theme_button()
        for btn, label in self._vertical_buttons:
            btn.setText(trc("search category", label))
        self._scope_label.setText(tr("Scope") + ":")
        self._sort_label.setText(tr("Sort") + ":")
        # Rebuild the sort combo, preserving the current selection by its data value.
        current = self._sort_combo.currentData()
        self._sort_combo.blockSignals(True)
        self._sort_combo.clear()
        for label, mode in self._sort_options:
            self._sort_combo.addItem(trc("sort order", label), mode.value)
        self._sort_combo.setCurrentIndex(max(0, self._sort_combo.findData(current)))
        self._sort_combo.blockSignals(False)
        self._refresh_scope_combo()
        self._browser_action.setText(tr("Browser setup"))
        self._history_action.setText(tr("History"))
        self._settings_action.setText(tr("Settings"))
        self._about_action.setText(tr("About"))
        self._refresh_server_labels()
        if self._tray is not None:
            self._tray_show_action.setText(tr("Show window"))
            self._tray_quit_action.setText(tr("Quit SearchMob"))
        self._summary_footer.setText(tr("From Wikipedia"))
        self._answer_header.setText(tr("AI answer (local)"))
        self._answer_footer.setText(
            tr("Generated on your device from the results below. May be inaccurate.")
        )
        self._empty_heading.setText(tr("Search the web privately"))
        self._empty_subtitle.setText(
            tr(
                "Results are aggregated across engines on this device. "
                "Nothing is stored by default."
            )
        )
        self._update_dismiss.setToolTip(tr("Dismiss until the next check"))
        self._update_btn.setText(tr("Update"))
        if self._pending_update is not None:
            version, _url = self._pending_update
            self._update_label.setText(tr("SearchMob {version} is available.", version=version))
        else:
            self._update_label.setText(tr("An update is available."))

    # --- Summary card ------------------------------------------------------------------------

    def _build_summary_card(self) -> QFrame:
        """A knowledge-panel card (title link, description, extract) for the Wikipedia summary."""
        card = QFrame()
        card.setObjectName("summaryCard")
        card.setProperty("role", "card")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        col = QVBoxLayout(card)
        col.setSpacing(4)
        self._summary_title = QLabel()
        self._summary_title.setTextFormat(Qt.TextFormat.RichText)
        self._summary_title.setOpenExternalLinks(False)
        self._summary_title.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        title_font = self._summary_title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 2)
        self._summary_title.setFont(title_font)
        self._summary_desc = QLabel()
        self._summary_desc.setProperty("role", "muted")
        self._summary_extract = QLabel()
        self._summary_extract.setWordWrap(True)
        self._summary_footer = QLabel(tr("From Wikipedia"))
        self._summary_footer.setProperty("role", "muted")
        footer = self._summary_footer
        for w in (self._summary_title, self._summary_desc, self._summary_extract, footer):
            col.addWidget(w)
        return card

    def _build_actions_card(self) -> QFrame:
        """A compact card of canonical media destinations ("Listen/Watch/Read/Play on ...").

        Rendered as one rich-text label (the verb plus brand links) so it wraps cleanly; clicking a
        link opens it in the browser. Every link is a locally-built search URL (nothing is fetched).
        """
        card = QFrame()
        card.setObjectName("actionsCard")
        card.setProperty("role", "card")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        col = QVBoxLayout(card)
        self._actions_label = QLabel()
        self._actions_label.setTextFormat(Qt.TextFormat.RichText)
        self._actions_label.setWordWrap(True)
        self._actions_label.setOpenExternalLinks(False)
        self._actions_label.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        col.addWidget(self._actions_label)
        return card

    def _show_actions(self, row: ActionsRow) -> None:
        label = _gui_row_label(row.category)
        links = " · ".join(
            f'<a href="{escape(link.url, quote=True)}">{escape(link.label)}</a>'
            for link in row.links
        )
        self._actions_label.setText(f"<b>{escape(label)}</b> {links}")
        self._actions_card.show()

    def _show_summary(self, box: SummaryBox) -> None:
        if box.url:
            href = escape(box.url, quote=True)
            self._summary_title.setText(f'<a href="{href}">{escape(box.title)}</a>')
        else:
            self._summary_title.setText(escape(box.title))
        self._summary_desc.setText(box.description)
        self._summary_desc.setVisible(bool(box.description))
        self._summary_extract.setText(box.extract)
        self._summary_card.show()

    def _build_answer_card(self) -> QFrame:
        """A card showing a locally-generated, results-grounded answer with citations."""
        card = QFrame()
        card.setObjectName("answerCard")
        card.setProperty("role", "card")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        col = QVBoxLayout(card)
        col.setSpacing(4)
        self._answer_header = QLabel(tr("AI answer (local)"))
        self._answer_header.setProperty("role", "heading")
        header = self._answer_header
        self._answer_body = QLabel()
        self._answer_body.setWordWrap(True)
        self._answer_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._answer_footer = QLabel(
            tr("Generated on your device from the results below. May be inaccurate.")
        )
        self._answer_footer.setProperty("role", "muted")
        footer = self._answer_footer
        for w in (header, self._answer_body, footer):
            col.addWidget(w)
        return card

    def _maybe_generate_answer(self, query: str, results: list[SearchResult]) -> None:
        """Stream a local-model answer (when enabled and ready) into the card as it is generated."""
        prefs = self._prefs_store.load()
        config = LlmConfig(
            enabled=prefs.llm_enabled,
            base_url=prefs.llm_base_url,
            model=prefs.llm_model,
        )
        # Each request gets a new id; deltas/finish from a superseded search are then ignored.
        self._answer_gen += 1
        gen = self._answer_gen
        self._answer_accum = ""
        if not config.ready or not results:
            self._answer_card.hide()
            return
        # Show an immediate "thinking" state; the first streamed token replaces it.
        self._answer_body.setText(tr("Thinking ..."))
        self._answer_card.show()
        grounding = list(results)

        async def _run() -> str | None:
            # on_delta runs on the worker thread; emitting a signal hops safely to the GUI thread.
            return await stream_answer(
                config, query, grounding, lambda piece: self._answer_delta.emit(gen, piece)
            )

        worker: AsyncWorker[str | None] = AsyncWorker(_run)
        worker.signals.finished.connect(lambda payload, g=gen: self._answer_final.emit(g, payload))
        worker.signals.failed.connect(lambda _exc, g=gen: self._answer_final.emit(g, None))
        worker.start(self._pool)

    def _on_answer_delta(self, gen: int, text: str) -> None:
        """A streamed token arrived (GUI thread): append it to the card."""
        if gen != self._answer_gen:
            return  # a newer search has superseded this stream
        self._answer_accum += text
        self._answer_body.setText(self._answer_accum)
        self._answer_card.show()

    def _on_answer_final(self, gen: int, payload: object) -> None:
        """The stream finished (GUI thread): set the full text, or hide if nothing was produced."""
        if gen != self._answer_gen:
            return
        if isinstance(payload, str) and payload.strip():
            self._answer_body.setText(payload)
            self._answer_card.show()
        elif not self._answer_accum:
            self._answer_card.hide()

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

        self._empty_heading = QLabel(tr("Search the web privately"))
        self._empty_heading.setProperty("role", "heading")
        self._empty_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_heading)

        self._empty_subtitle = QLabel(
            tr(
                "Results are aggregated across engines on this device. "
                "Nothing is stored by default."
            )
        )
        self._empty_subtitle.setProperty("role", "muted")
        self._empty_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_subtitle.setWordWrap(True)
        layout.addWidget(self._empty_subtitle)
        return widget

    # --- Tray --------------------------------------------------------------------------------

    def _setup_tray(self) -> None:
        """Create the tray icon and its menu, if the host OS exposes a system tray."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray = QSystemTrayIcon(app_icon(), self)
        tray.setToolTip("SearchMob Desktop")

        menu = QMenu(self)
        self._tray_show_action = QAction(tr("Show window"), self)
        self._tray_show_action.triggered.connect(self._show_from_tray)
        menu.addAction(self._tray_show_action)

        self._tray_server_action = QAction(tr("Start server"), self)
        self._tray_server_action.triggered.connect(self._on_toggle_server)
        menu.addAction(self._tray_server_action)

        menu.addSeparator()
        self._tray_quit_action = QAction(tr("Quit SearchMob"), self)
        self._tray_quit_action.triggered.connect(self._quit_from_tray)
        menu.addAction(self._tray_quit_action)

        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        # Clicking the "update available" notification starts the update. messageClicked does not
        # say which fired, so _on_notification_clicked no-ops unless an update is actually pending.
        tray.messageClicked.connect(self._on_notification_clicked)
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

    # --- Update notifier ---------------------------------------------------------------------

    def _build_update_banner(self) -> QFrame:
        """A dismissible "update available" bar with an Update button and a close affordance."""
        bar = QFrame()
        bar.setObjectName("updateBanner")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 8, 8)
        row.setSpacing(10)
        self._update_label = QLabel(tr("An update is available."))
        self._update_btn = QPushButton(tr("Update"))
        self._update_btn.clicked.connect(self._on_update_clicked)
        self._update_dismiss = QPushButton("✕")  # MULTIPLICATION X, a compact close glyph
        dismiss = self._update_dismiss
        dismiss.setProperty("role", "dismiss")
        dismiss.setToolTip(tr("Dismiss until the next check"))
        dismiss.setFixedWidth(34)
        dismiss.clicked.connect(self._update_banner_dismiss)
        row.addWidget(self._update_label, stretch=1)
        row.addWidget(self._update_btn)
        row.addWidget(dismiss)
        bar.hide()
        return bar

    @staticmethod
    def _current_version_code() -> int:
        parsed = VersionTag.parse(__version__)
        return parsed.to_version_code() if parsed is not None else 0

    def _surface_pending_update_from_prefs(self, prefs: object) -> None:
        """Show the banner for a prefs-recorded pending update, if still newer than this build."""
        version = getattr(prefs, "pending_update_version", "")
        url = getattr(prefs, "pending_update_url", "")
        if not version or not url:
            return
        parsed = VersionTag.parse(version)
        if parsed is None or parsed.to_version_code() <= self._current_version_code():
            return
        # Notify on launch too: the app being open with an update available is exactly the case the
        # system notification is for. _surface_update guards against repeating it within a session.
        self._surface_update(version, url, notify=True)

    def _surface_update(self, version: str, url: str, *, notify: bool) -> None:
        """Show/refresh the banner and optionally post a one-per-session system notification."""
        self._pending_update = (version, url)
        self._update_label.setText(tr("SearchMob {version} is available.", version=version))
        self._update_btn.setEnabled(True)
        self._update_btn.setText(tr("Update"))
        self._update_banner.show()
        if notify and not self._update_notified:
            self._update_notified = True
            self._post_update_notification(version)

    def _post_update_notification(self, version: str) -> None:
        """Post a native system notification through the tray icon, when one is available."""
        if self._tray is not None and QSystemTrayIcon.supportsMessages():
            self._tray.showMessage(
                tr("Update available"),
                tr("SearchMob {version} is available. Click here to update.", version=version),
                app_icon(),
                8000,
            )

    def _on_notification_clicked(self) -> None:
        """The tray notification was clicked: bring the window forward and start the update."""
        if self._pending_update is None:
            return
        self._show_from_tray()
        self._on_update_clicked()

    def _update_banner_dismiss(self) -> None:
        # Hide for this session only. The pending record stays in prefs, so the banner returns on
        # the next launch or check until the user actually updates.
        self._update_banner.hide()

    def showEvent(self, event):  # type: ignore[no-untyped-def]
        # Kick off the throttled update check the first time the window is shown (a real launch),
        # not on construction, so headless/widget tests that never show it stay offline.
        super().showEvent(event)
        if not self._update_check_started:
            self._update_check_started = True
            QTimer.singleShot(0, self._start_update_check)
            # Keep re-checking while the window stays open so a release published AFTER launch is
            # still surfaced without a relaunch. The ~daily throttle in `check_if_due` means almost
            # every tick is a no-op (no network); this just bounds the notification lag to the tick.
            self._update_recheck_timer = QTimer(self)
            self._update_recheck_timer.setInterval(_UPDATE_RECHECK_INTERVAL_MS)
            self._update_recheck_timer.timeout.connect(self._start_update_check)
            self._update_recheck_timer.start()

    def _start_update_check(self) -> None:
        """Run the throttled GitHub check off-thread; surface a newer release if found."""

        async def _probe() -> object:
            prefs = self._prefs_store.load()
            now_ms = int(time.time() * 1000)
            info, stamped = await check_if_due(
                prefs,
                self._current_version_code(),
                now_ms=now_ms,
                client_factory=lambda: make_privacy_client(4.0),
            )
            return prefs, info, stamped

        worker: AsyncWorker[object] = AsyncWorker(_probe)
        worker.signals.finished.connect(self._on_update_check_done)
        worker.signals.failed.connect(lambda _msg: None)  # fail-soft: a check error stays silent
        worker.start(self._pool)

    def _on_update_check_done(self, payload: object) -> None:
        """Persist the check result (stamp + pending fields) and surface a newer release."""
        if not (isinstance(payload, tuple) and len(payload) == 3):
            return
        prefs, info, stamped = payload
        reconciled = reconcile_pending_update(prefs, info, stamped=stamped)
        if reconciled != prefs:
            try:
                self._prefs_store.save(reconciled)
            except OSError:
                pass
        if info is not None:
            self._surface_update(info.latest_version.formatted(), info.release_url, notify=True)

    def _on_update_clicked(self) -> None:
        """Fetch-and-hand-off: download + verify the installer, or open the release page."""
        if self._pending_update is None:
            return
        version, url = self._pending_update
        self._update_btn.setEnabled(False)
        self._update_label.setText(tr("Downloading SearchMob {version} …", version=version))
        system = sys.platform

        async def _run() -> object:
            # A generous read timeout: the installer is large, and httpx applies the timeout per
            # network operation (max gap between bytes), not to the whole transfer.
            async with make_privacy_client(60.0) as client:
                info = await fetch_latest(client)
                if info is None:
                    return ("page", url)
                asset = info.asset_for_system(system)
                sums = info.checksums_asset()
                if asset is None or sums is None:
                    # Linux (multiple package formats) or a release without a usable asset/checksum:
                    # hand off to the release page so the user picks the right download.
                    return ("page", info.release_url)
                path = await download_and_verify(client, asset, sums, default_download_dir())
                return ("file", str(path))

        worker: AsyncWorker[object] = AsyncWorker(_run)
        worker.signals.finished.connect(
            lambda payload, v=version, u=url: self._on_update_download_done(payload, v, u)
        )
        worker.signals.failed.connect(
            lambda msg, v=version, u=url: self._on_update_download_failed(msg, v, u)
        )
        worker.start(self._pool)

    def _on_update_download_done(self, payload: object, version: str, url: str) -> None:
        self._update_btn.setEnabled(True)
        self._update_label.setText(tr("SearchMob {version} is available.", version=version))
        kind, value = payload if isinstance(payload, tuple) and len(payload) == 2 else ("page", url)
        if kind == "file":
            # Hand off to the OS: opening the installer mounts the .dmg / launches the .msi. While
            # builds are unsigned, Gatekeeper / SmartScreen will still prompt; that is unavoidable.
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(value)):
                # Could not auto-open it: reveal the folder so the user can run it themselves.
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(value).parent)))
            self.statusBar().showMessage(tr("Downloaded installer: {path}", path=value))
        else:
            QDesktopServices.openUrl(QUrl(value))

    def _on_update_download_failed(self, message: str, version: str, url: str) -> None:
        self._update_btn.setEnabled(True)
        self._update_label.setText(tr("SearchMob {version} is available.", version=version))
        QMessageBox.warning(
            self,
            tr("Update download failed"),
            f"{message}\n\n" + tr("Opening the release page so you can download it manually."),
        )
        QDesktopServices.openUrl(QUrl(url))

    # --- Search ------------------------------------------------------------------------------

    def _on_submit(self) -> None:
        query = self._query_input.text().strip()
        if not query:
            return
        self._last_query = query
        self._status_label.setText(tr("Searching ..."))
        self._didyoumean.hide()
        self._summary_card.hide()
        self._answer_card.hide()
        self._results.clear()
        self._search_btn.setEnabled(False)

        prefs = self._prefs_store.load()
        engines = build_engines_from_prefs(prefs)
        # Google-style operators (site:/intitle:/before:/etc., see query_operators) are parsed once
        # here: the engine query (scoped for the active vertical) goes upstream, while the
        # operator-free clean text drives scoring, sort, the summary lookup, and the corrector so
        # a scoping clause never throws those off.
        parsed = parse_query_operators(query)
        self._last_clean_query = parsed.clean_text
        self._last_has_operators = parsed.has_operators
        ctx = EngineContext(
            query=transform_query(parsed.engine_query, self._vertical),
            max_results=DEFAULT_POOL_SIZE,
            timeout_seconds=5.0,
            ranking_terms=parsed.clean_text,
        )
        summary_enabled = prefs.summary_enabled

        async def _run() -> tuple[list[SearchResult], SummaryBox | None, AggregateOutcome]:
            # Fetch the contextual summary concurrently with the metasearch so it adds no latency.
            # The lookup uses the operator-free text: an operator-laden query never names an entity.
            summary_task = (
                asyncio.ensure_future(summary_for_query(parsed.clean_text))
                if summary_enabled
                else None
            )
            outcome = await aggregate_with_status(ctx, engines)
            # Operators the engines cannot be trusted to honor are enforced locally over the merged
            # results (drops only; scores untouched), before sort/personalization/rules see them.
            results = outcome.results
            if parsed.has_filters:
                results = [
                    r for r in results if parsed.matches(r.title, r.url, r.snippet, r.published)
                ]
            summary = await summary_task if summary_task is not None else None
            return results, summary, outcome

        worker: AsyncWorker[tuple[list[SearchResult], SummaryBox | None, AggregateOutcome]] = (
            AsyncWorker(_run)
        )
        worker.signals.finished.connect(self._on_results_ready)
        worker.signals.failed.connect(self._on_search_failed)
        # Record the search in the (in-memory) history store if enabled. The store handles the
        # disabled-no-op case itself.
        try:
            self._history_store.add(query)
        except Exception:
            pass
        worker.start(self._pool)

    def _on_results_ready(self, payload: object) -> None:
        self._search_btn.setEnabled(True)
        # The worker returns (results, summary, outcome). Show the summary card regardless of count.
        results: object = payload
        summary: object = None
        if isinstance(payload, tuple) and len(payload) == 3:
            results, summary, outcome = payload
            self._engine_status = outcome.engines if isinstance(outcome, AggregateOutcome) else ()
        if isinstance(summary, SummaryBox):
            self._show_summary(summary)
        else:
            self._summary_card.hide()
        # Media actions row: for a resolved media entity (toggle on), show the canonical-platform
        # card and record the category for the bounded promotion in `_apply_ranking_and_show`.
        self._media_category = None
        self._actions_card.hide()
        if self._prefs_store.load().media_actions_enabled and isinstance(summary, SummaryBox):
            category = detect_category(summary.description)
            if category is not None:
                self._media_category = category
                self._show_actions(build_actions_row(category, summary.title, summary.url))
        if not isinstance(results, list):
            self._status_label.setText(tr("Search failed: unexpected result type."))
            self._body.setCurrentWidget(self._empty_state)
            return
        if not results:
            self._raw_results = []
            summary, tooltip = self._engine_status_suffix()
            no_results = tr("No results found.")
            self._status_label.setText(f"{no_results}  ·  {summary}" if summary else no_results)
            self._status_label.setToolTip(tooltip)
            self._body.setCurrentWidget(self._empty_state)
            self._maybe_show_correction()
            self._answer_card.hide()
            return
        self._raw_results = results
        self._body.setCurrentWidget(self._results)
        self._apply_ranking_and_show()
        self._maybe_show_correction()
        # Ground the optional local-AI answer on the original query and the freshly ranked results.
        self._maybe_generate_answer(self._last_query, results)

    def _apply_ranking_and_show(self) -> None:
        """Sort, then re-rank the last raw results with the current rules; update view + status."""
        # Sort first (relevance/date/freshness blend), then bucket by the user's rules so PIN/RAISE
        # are honored while preserving the chosen order within each bucket.
        # The freshness heuristic and the click model reason about subject terms, so both get the
        # operator-free clean text (a site:/filetype: clause is not a freshness keyword).
        now_ms = int(time.time() * 1000)
        ordered = sort_results(self._raw_results, self._sort_mode, self._last_clean_query, now_ms)
        # Then nudge by the learned click model (between sort and rules, so PIN/RAISE/BLOCK win).
        if self._personalization_enabled:
            ordered = personalize_reorder(
                ordered,
                lambda r: host_of_url(r.url),
                self._last_clean_query,
                self._personalization,
                now_ms,
            )
        # Media promotion: nudge the detected category's canonical platforms up (bounded), after
        # relevance/personalization and before the user's rules so pin/raise/block still win.
        if self._media_category is not None:
            ordered = promote_media(ordered, self._media_category)
        ranked = apply_ranking(
            ordered,
            self._ranking_rules,
            host_of=lambda r: host_of_url(r.url),
            text_of=lambda r: f"{r.title} {r.snippet}",
            slop_domains=load_slop_domains(),
            slop_mode=self._prefs_store.load().ai_slop_mode,
        )
        self._displayed_results = ranked
        self._results.set_results(ranked)
        hidden = len(self._raw_results) - len(ranked)
        base = trn(len(ranked), "{n} result", "{n} results")
        if hidden > 0:
            hid = trn(hidden, "{n} hidden by your rules", "{n} hidden by your rules")
            text = f"{base} ({hid})."
        else:
            text = f"{base}."
        summary, tooltip = self._engine_status_suffix()
        if summary:
            text = f"{text}  ·  {summary}"
        self._status_label.setText(text)
        self._status_label.setToolTip(tooltip)

    def _engine_status_suffix(self) -> tuple[str, str]:
        """Return `(summary, tooltip)` for the last search's per-engine outcome, or `("", "")`.

        `summary` is the muted "N of M engines responded" line appended to the status text;
        `tooltip` lists each engine's outcome (the per-engine detail on demand, shown on hover).
        Both are computed from on-device data and are never persisted or transmitted.
        """
        if not self._engine_status:
            return "", ""
        total = len(self._engine_status)
        responded = sum(1 for o in self._engine_status if o.status != "failed")
        summary = tr("{responded} of {total} engines responded", responded=responded, total=total)
        lines: list[str] = []
        for outcome in self._engine_status:
            if outcome.status == "contributed":
                detail = trn(outcome.count, "{n} result", "{n} results")
            elif outcome.status == "empty":
                detail = trc("engine status", "no results")
            else:
                detail = trc("engine status", "failed")
            lines.append(f"{outcome.name} — {detail}")
        return summary, "\n".join(lines)

    def _on_vertical_clicked(self, button: QPushButton) -> None:
        """A category tab was clicked: switch vertical and re-run the search."""
        self._vertical = Vertical.from_value(button.property("vertical"))
        # Re-run only when there is a query in the box; _on_submit no-ops on empty input.
        if self._query_input.text().strip():
            self._on_submit()

    def _on_sort_changed(self) -> None:
        """Sort control changed: persist the choice and re-sort the current results in place."""
        self._sort_mode = SortMode.from_value(self._sort_combo.currentData())
        try:
            from dataclasses import replace

            prefs = self._prefs_store.load()
            self._prefs_store.save(replace(prefs, sort_mode=self._sort_mode.value))
        except OSError:
            pass
        if self._raw_results:
            self._apply_ranking_and_show()

    def _refresh_scope_combo(self) -> None:
        """Rebuild the scope selector from the current rules; hide it when no lenses exist."""
        self._scope_combo.blockSignals(True)
        self._scope_combo.clear()
        self._scope_combo.addItem(tr("No scope"), "")
        for lens in self._ranking_rules.lenses:
            self._scope_combo.addItem(lens.name, lens.name)
        active = self._ranking_rules.active_lens or ""
        idx = self._scope_combo.findData(active)
        self._scope_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._scope_combo.blockSignals(False)
        has_lenses = bool(self._ranking_rules.lenses)
        self._scope_label.setVisible(has_lenses)
        self._scope_combo.setVisible(has_lenses)

    def _on_scope_changed(self) -> None:
        """Scope control changed: set the active lens, persist it, and re-rank in place."""
        name = self._scope_combo.currentData() or None
        self._ranking_rules = self._ranking_rules.with_active_lens(name)
        save_ranking_rules(self._ranking_rules)
        if self._raw_results:
            self._apply_ranking_and_show()

    def _on_rule_requested(self, domain: str, rule: RankRule) -> None:
        """A right-click ranking action on a result domain: persist it and re-rank in place."""
        if rule == RankRule.NORMAL:
            self._ranking_rules = self._ranking_rules.without_domain_rule(domain)
        else:
            self._ranking_rules = self._ranking_rules.with_domain_rule(domain, rule)
        save_ranking_rules(self._ranking_rules)
        if self._raw_results:
            self._apply_ranking_and_show()

    def _on_result_activated(self, url: str, row: int) -> None:
        """A result was opened: learn from the click (clicked over skipped-above) when enabled.

        Uses the displayed order so the model sees the same ranks the user saw. Persisting to the
        vault is best-effort; `save_personalization` is a no-op when the vault is unavailable.
        """
        if not self._personalization_enabled or not url:
            return
        if row < 0 or row >= len(self._displayed_results):
            return
        hosts = [host_of_url(r.url) for r in self._displayed_results]
        update_from_click(
            self._personalization,
            hosts,
            row,
            query_terms(self._last_clean_query),
            int(time.time() * 1000),
        )
        save_personalization(self._personalization)

    def _maybe_show_correction(self) -> None:
        """Offer a 'Did you mean: X' link when the on-device corrector suggests one.

        Skipped for an operator-laden query: the corrector reasons about English word spelling,
        not query syntax, and would just mangle the operators.
        """
        if self._last_has_operators:
            self._didyoumean.hide()
            return
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
        self._status_label.setText(tr("Search failed: {message}", message=message))
        self._body.setCurrentWidget(self._empty_state)

    # --- Server ------------------------------------------------------------------------------

    def start_server(self) -> None:
        """Start the local server if it is not already running.

        Called once on launch by `run_gui` so SearchMob is reachable (and usable as the browser's
        search engine) the moment the app opens, without the user having to start it by hand. A
        no-op if a server is already running, and fail-soft: a bind error surfaces through the usual
        `serverError` handler rather than blocking launch.
        """
        if not self._server.is_running:
            self._server.start()

    def _on_toggle_server(self) -> None:
        if self._server.is_running:
            self._server.stop()
        else:
            self._server.start()

    def _refresh_server_labels(self) -> None:
        """Set the toolbar/tray/status-bar server text from the current state (and the locale).

        Centralized so a language change can re-derive these live by re-calling it, keeping the
        running/stopped/external wording translated and consistent.
        """
        if self._server.is_running:
            bound = self._server.bound_url or ""
            external = self._server.is_external
            if external:
                # The background service owns this server; the app is only reusing it. Do not offer
                # to stop a process the app does not own.
                self._toggle_server_action.setText(tr("Background service running"))
                self._toggle_server_action.setEnabled(False)
                self.statusBar().showMessage(tr("Using the background service at {url}", url=bound))
            else:
                self._toggle_server_action.setText(tr("Stop server"))
                self._toggle_server_action.setEnabled(True)
                self.statusBar().showMessage(tr("Server running at {url}", url=bound))
            if self._tray is not None:
                self._tray_server_action.setText(
                    tr("Background service") if external else tr("Stop server")
                )
                self._tray_server_action.setEnabled(not external)
                self._tray.setToolTip(f"SearchMob Desktop - {bound}")
        else:
            self._toggle_server_action.setText(tr("Start server"))
            self._toggle_server_action.setEnabled(True)
            if self._tray is not None:
                self._tray_server_action.setText(tr("Start server"))
                self._tray_server_action.setEnabled(True)
                self._tray.setToolTip("SearchMob Desktop")

    def _on_server_started(self, port: int) -> None:
        self._refresh_server_labels()

    def _on_server_stopped(self) -> None:
        self._refresh_server_labels()
        self.statusBar().showMessage(tr("Server stopped."))

    def _on_server_error(self, message: str) -> None:
        self._toggle_server_action.setText(tr("Start server"))
        self.statusBar().showMessage(tr("Server error."))
        if self._tray is not None:
            self._tray_server_action.setText(tr("Start server"))
        QMessageBox.warning(self, tr("Server error"), message)

    # --- Dialogs -----------------------------------------------------------------------------

    def _update_theme_button(self) -> None:
        """Label the toggle with the theme it switches to: a sun for Light, a moon for Dark."""
        is_dark = active_theme().mode == DARK
        self._theme_btn.setText("☀ " + tr("Light") if is_dark else "☾ " + tr("Dark"))

    def _on_toggle_theme(self) -> None:
        """Flip the mode between light and dark, persist it, and re-style the app live.

        The picker chooses which named theme fills each slot; this just swaps which slot is shown,
        so toggling moves between the user's chosen light and dark themes.
        """
        from dataclasses import replace

        prefs = self._prefs_store.load()
        new_mode = "light" if active_theme().mode == DARK else "dark"
        try:
            self._prefs_store.save(replace(prefs, theme=new_mode))
        except OSError:
            pass
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            apply_theme(
                app,  # type: ignore[arg-type]
                new_mode,
                prefs.light_theme,
                prefs.dark_theme,
                prefs.font_point_size,
            )
        self._update_theme_button()

    def _on_open_settings(self) -> None:
        dialog = SettingsDialog(
            prefs_store=self._prefs_store,
            server_controller=self._server,
            history_store=self._history_store,
            parent=self,
        )

        def _on_theme_changed(_theme: str) -> None:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                # Reload prefs so a changed slot theme or font size (not just the mode) is applied.
                # `QApplication.instance()` returns `QCoreApplication`; cast for the type checker.
                prefs = self._prefs_store.load()
                apply_theme(
                    app,  # type: ignore[arg-type]
                    prefs.theme,
                    prefs.light_theme,
                    prefs.dark_theme,
                    prefs.font_point_size,
                )
            # Keep the homepage toggle's sun/moon label in sync with the Settings change.
            self._update_theme_button()

        def _on_rules_changed() -> None:
            # The ranking tab edited the vault-stored rules; reload, refresh the scope selector
            # (lenses may have been added/removed), and re-rank current results.
            self._ranking_rules = load_ranking_rules()
            self._refresh_scope_combo()
            if self._raw_results:
                self._apply_ranking_and_show()

        dialog.themeChanged.connect(_on_theme_changed)
        dialog.rulesChanged.connect(_on_rules_changed)
        dialog.exec()

        # The personalization toggle / export-import / reset may have changed in Settings; pick up
        # the new enabled state and reload the model (so a live toggle takes effect immediately).
        prefs_after = self._prefs_store.load()
        # A "Check now" in Settings may have found (or cleared) a pending update; reflect it without
        # re-notifying (the user is already here). Hide the banner if the pending record is gone.
        if prefs_after.pending_update_version and prefs_after.pending_update_url:
            self._surface_pending_update_from_prefs(prefs_after)
        else:
            self._pending_update = None
            self._update_banner.hide()
        self._personalization_enabled = prefs_after.personalization_enabled
        self._personalization = (
            load_personalization()
            if prefs_after.personalization_enabled
            else PersonalizationModel()
        )
        if self._raw_results:
            self._apply_ranking_and_show()

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
