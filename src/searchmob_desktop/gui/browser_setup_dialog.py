"""Browser-setup wizard, the desktop translation of the Android `BrowserSetupScreen`.

Three URL cards (visit, search template, suggestion template), one open-in-browser button, and
per-browser instruction cards. The exact wording is condensed from `strings.xml` but the steps
are the same; nothing here writes to disk or pings the network, so the dialog is safe to leave
open while the rest of the GUI runs.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QClipboard, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def _setup_urls(host: str, port: int) -> tuple[str, str, str]:
    """Return `(visit_url, search_template, suggestion_template)` for a bound `(host, port)`.

    Mirrors the Android `SetupUrls`; the `{searchTerms}` placeholder is what every modern browser
    expects, and matches what the OpenSearch descriptor advertises.
    """
    origin = f"http://{host}:{port}"
    return (
        f"{origin}/",
        f"{origin}/search?q={{searchTerms}}",
        f"{origin}/suggest?q={{searchTerms}}",
    )


class BrowserSetupDialog(QDialog):
    """Stateless setup dialog. Pass the live `(host, port)`."""

    def __init__(
        self,
        host: str,
        port: int | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Browser setup")
        self.setModal(True)
        self.resize(720, 720)

        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        host_widget = QWidget(scroll)
        layout = QVBoxLayout(host_widget)
        layout.setSpacing(12)

        if port is None:
            self._render_not_running(layout)
        else:
            visit, search_template, suggest_template = _setup_urls(host, port)
            intro = QLabel(
                "Make SearchMob your browser's default search engine. Open the page below "
                "once, then add SearchMob from your browser's search settings. When the "
                "browser asks for a search URL, paste the search template. When it asks for a "
                "Suggestion URL (Firefox and Chromium both have this field), paste the "
                "suggestion template so autocomplete works."
            )
            intro.setWordWrap(True)
            layout.addWidget(intro)

            self._add_url_card(layout, "Page to visit", visit)
            self._add_url_card(layout, "Search URL (paste with {searchTerms})", search_template)
            self._add_url_card(
                layout, "Suggestion URL (paste with {searchTerms})", suggest_template
            )

            open_btn = QPushButton("Open in browser")
            open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(visit)))
            layout.addWidget(open_btn)

            self._add_instructions(
                layout,
                "Any browser (the general method)",
                (
                    "Open the page above once. SearchMob advertises itself as a search "
                    "engine when you visit it.",
                    "Open your browser's search-engine settings.",
                    "Pick SearchMob if it appears, or add a custom engine using the search "
                    "template (keep {searchTerms} intact), then set it as default.",
                ),
            )
            self._add_instructions(
                layout,
                "Firefox family (Firefox, LibreWolf, Mull, IronFox)",
                (
                    "Menu -> Settings -> Search -> Default search engine -> Add search engine.",
                    "Name it SearchMob. Paste the Search URL into the Search string URL "
                    "field. Paste the Suggestion URL into the Search Suggestion API field. "
                    "Keep the {searchTerms} placeholders.",
                    "Save, then set SearchMob as the default search engine.",
                ),
            )
            self._add_instructions(
                layout,
                "Chromium browsers (Chrome, Brave, Edge, Vivaldi)",
                (
                    "Settings -> Search engine -> Manage search engines and site search -> Add.",
                    "Name it SearchMob and pick a Shortcut. Paste the Search URL into the "
                    "URL field, and paste the Suggestion URL into the Suggestion URL field. "
                    "Keep the {searchTerms} placeholders.",
                    "Save, then activate SearchMob as the default search engine.",
                ),
            )
            self._add_instructions(
                layout,
                "Other browsers (manual)",
                (
                    "In your browser's search-engine settings, add a custom engine.",
                    "Paste the search template as the query URL. Keep the {searchTerms} "
                    "placeholder intact.",
                    "Set the new engine as your default.",
                ),
            )
            self._add_instructions(
                layout,
                "Show search suggestions (optional)",
                (
                    "Make sure you pasted the Suggestion URL above into the browser's "
                    "Suggestion URL field when you added SearchMob.",
                    "Browsers also keep their own Show search suggestions toggle. Firefox "
                    "family: menu -> Settings -> Search -> Show search suggestions. "
                    "Chromium: Settings -> Search engine -> Show search suggestions.",
                    "SearchMob suggests from your local history by default. For live web "
                    "autocomplete, open Settings -> Suggestions and turn on Live "
                    "suggestions from the web.",
                ),
            )

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout.addLayout(bottom)

        scroll.setWidget(host_widget)
        outer.addWidget(scroll)

    @staticmethod
    def _render_not_running(layout: QVBoxLayout) -> None:
        title = QLabel("Server not running")
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        body = QLabel(
            "The on-device search server is not running, so there is no address to add yet. "
            "Start the server from the main window, then come back here."
        )
        body.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(body)

    def _add_url_card(self, layout: QVBoxLayout, label: str, url: str) -> None:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        row = QHBoxLayout(card)
        text_col = QVBoxLayout()
        label_widget = QLabel(label)
        label_widget.setProperty("role", "muted")
        url_widget = QLabel(url)
        url_widget.setProperty("role", "url")
        url_widget.setTextInteractionFlags(
            url_widget.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        url_widget.setWordWrap(True)
        text_col.addWidget(label_widget)
        text_col.addWidget(url_widget)
        row.addLayout(text_col, stretch=1)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(lambda checked=False, value=url: self._copy(value))
        row.addWidget(copy_btn)
        layout.addWidget(card)

    @staticmethod
    def _add_instructions(layout: QVBoxLayout, title: str, steps: tuple[str, ...]) -> None:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        body = QVBoxLayout(card)
        title_widget = QLabel(title)
        title_font = title_widget.font()
        title_font.setBold(True)
        title_widget.setFont(title_font)
        body.addWidget(title_widget)
        for i, step in enumerate(steps, start=1):
            step_widget = QLabel(f"{i}. {step}")
            step_widget.setWordWrap(True)
            body.addWidget(step_widget)
        layout.addWidget(card)

    def _copy(self, value: str) -> None:
        clipboard: QClipboard | None = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(value)
        # Brief toast-like confirmation; QMessageBox.information is the lowest-friction option
        # without dragging in a custom non-modal snackbar.
        QMessageBox.information(self, "Copied", "Copied to clipboard.")
