"""Browser-setup wizard, the desktop translation of the Android `BrowserSetupScreen`.

Three URL cards (visit, search template, suggestion template), one open-in-browser button, and
per-browser instruction cards. The exact wording is condensed from `strings.xml` but the steps
are the same; nothing here writes to disk or pings the network, so the dialog is safe to leave
open while the rest of the GUI runs.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QUrl
from PySide6.QtGui import QClipboard, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from searchmob_desktop.i18n import tr


def _setup_urls(host: str, port: int, token: str | None = None) -> tuple[str, str, str]:
    """Return `(visit_url, search_template, suggestion_template)` for a bound `(host, port)`.

    The templates use the `%s` search-term placeholder, which is what Firefox-family and Chromium
    browsers expect in their "add a search engine" dialogs. (The `{searchTerms}` form is only for
    the OpenSearch descriptor the server advertises for auto-detect; pasting it into a manual Add
    dialog fails with "Try including %s in place of the search term".)

    When `token` is set (network mode), it is appended as `&token=<token>` to the search and
    suggestion templates so a browser configured off-loopback is not rejected with 403. The visit
    URL stays token-free (the `/` route is open). Loopback setups pass `token=None` for clean URLs.
    """
    origin = f"http://{host}:{port}"
    suffix = f"&token={token}" if token else ""
    return (
        f"{origin}/",
        f"{origin}/search?q=%s{suffix}",
        f"{origin}/suggest?q=%s{suffix}",
    )


def choose_setup_host(
    *,
    network_enabled: bool,
    configured_hostnames: Sequence[str] = (),
    local_names: Sequence[str] = (),
) -> str:
    """Pick the host to show in the setup URLs.

    Loopback (the common case): use `localhost`, which every browser resolves to the loopback
    address and which the server's Host allowlist accepts. In network mode, prefer a configured
    hostname (e.g. a Tailscale MagicDNS name), then the machine's own detected name, so other
    devices reach the server by a friendly name; fall back to the loopback IP if neither is known.
    """
    if not network_enabled:
        return "localhost"
    for name in (*configured_hostnames, *local_names):
        cleaned = name.strip()
        if cleaned:
            return cleaned
    return "127.0.0.1"


class BrowserSetupDialog(QDialog):
    """Stateless setup dialog. Pass the live `(host, port)`."""

    def __init__(
        self,
        host: str,
        port: int | None,
        parent: QWidget | None = None,
        token: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Browser setup"))
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
            visit, search_template, suggest_template = _setup_urls(host, port, token)
            intro = QLabel(
                tr(
                    "Make SearchMob your browser's default search engine. The easiest way: open"
                    " the page below once, then add SearchMob from your browser's search settings"
                    " (it is offered automatically). If you add it by hand instead, paste the"
                    " search template into the URL field and the suggestion template into the"
                    " Suggestion URL field. The %s in each template is where the browser drops"
                    " your search term; leave it as it is."
                )
            )
            intro.setWordWrap(True)
            layout.addWidget(intro)

            self._add_url_card(layout, tr("Page to visit"), visit)
            self._add_url_card(
                layout, tr("Search URL (uses %s for the search term)"), search_template
            )
            self._add_url_card(
                layout, tr("Suggestion URL (uses %s for the search term)"), suggest_template
            )

            open_btn = QPushButton(tr("Open in browser"))
            open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(visit)))
            layout.addWidget(open_btn)

            self._add_instructions(
                layout,
                tr("Any browser (the general method)"),
                (
                    tr(
                        "Open the page above once. SearchMob advertises itself as a search"
                        " engine when you visit it."
                    ),
                    tr("Open your browser's search-engine settings."),
                    tr(
                        "Pick SearchMob if it appears (no URL to type). Otherwise add a custom"
                        " engine and paste the search template, leaving the %s placeholder"
                        " intact, then set it as default."
                    ),
                ),
            )
            self._add_instructions(
                layout,
                tr("Firefox family (Firefox, LibreWolf, Mull, IronFox)"),
                (
                    tr(
                        "Easiest: after visiting the page above, go to Menu -> Settings ->"
                        " Search and SearchMob can be added directly (it carries the right URLs)."
                    ),
                    tr(
                        "To add it by hand: Settings -> Search -> Add search engine. Name it"
                        " SearchMob, paste the Search URL into the Engine URL field, and the"
                        " Suggestion URL into the Suggestions URL field. Firefox uses %s for the"
                        " search term (not {searchTerms}); leave the %s in the templates as it is."
                    ),
                    tr("Save, then set SearchMob as the default search engine."),
                ),
            )
            self._add_instructions(
                layout,
                tr("Chromium browsers (Chrome, Brave, Edge, Vivaldi)"),
                (
                    tr(
                        "Settings -> Search engine -> Manage search engines and site search -> Add."
                    ),
                    tr(
                        "Name it SearchMob and pick a Shortcut. Paste the Search URL into the"
                        " URL field, and paste the Suggestion URL into the Suggestion URL field."
                        " Chromium uses %s for the search term; leave the %s in the templates"
                        " as it is."
                    ),
                    tr("Save, then activate SearchMob as the default search engine."),
                ),
            )
            self._add_instructions(
                layout,
                tr("Other browsers (manual)"),
                (
                    tr("In your browser's search-engine settings, add a custom engine."),
                    tr(
                        "Paste the search template as the query URL, leaving the %s placeholder"
                        " intact (most browsers use %s for the search term)."
                    ),
                    tr("Set the new engine as your default."),
                ),
            )
            self._add_instructions(
                layout,
                tr("Show search suggestions (optional)"),
                (
                    tr(
                        "Make sure you pasted the Suggestion URL above into the browser's"
                        " Suggestion URL field when you added SearchMob."
                    ),
                    tr(
                        "Browsers also keep their own Show search suggestions toggle. Firefox"
                        " family: menu -> Settings -> Search -> Show search suggestions."
                        " Chromium: Settings -> Search engine -> Show search suggestions."
                    ),
                    tr(
                        "SearchMob suggests from your local history by default. For live web"
                        " autocomplete, open Settings -> Suggestions and turn on Live"
                        " suggestions from the web."
                    ),
                ),
            )

        close = QPushButton(tr("Close"))
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout.addLayout(bottom)

        scroll.setWidget(host_widget)
        outer.addWidget(scroll)

    @staticmethod
    def _render_not_running(layout: QVBoxLayout) -> None:
        title = QLabel(tr("Server not running"))
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        body = QLabel(
            tr(
                "The on-device search server is not running, so there is no address to add yet."
                " Start the server from the main window, then come back here."
            )
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
        copy_btn = QPushButton(tr("Copy"))
        copy_btn.clicked.connect(
            lambda checked=False, value=url, field=url_widget: self._copy(value, field)
        )
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

    def _copy(self, value: str, field: QLabel) -> None:
        clipboard: QClipboard | None = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(value)
        # No modal: confirm inline by flashing a green outline on the field and floating a
        # checkmark over it that fades out. Far less interruptive than a dialog.
        self._flash_copied(field)

    # Success green that reads well on both the light and dark palettes.
    _COPIED_GREEN = "#2fae66"

    def _flash_copied(self, field: QLabel) -> None:
        """Briefly outline `field` in green and fade a checkmark over it, then restore."""
        base_style = field.styleSheet()
        field.setStyleSheet(
            f"{base_style}\nborder: 2px solid {self._COPIED_GREEN}; border-radius: 6px;"
        )

        # The checkmark is parented to the field so it positions in field coordinates; it must
        # not eat clicks meant for the selectable URL text underneath.
        badge = QLabel("✓", field)  # ✓
        badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        badge.setStyleSheet(
            f"color: {self._COPIED_GREEN}; font-size: 22px; font-weight: bold; "
            "background: transparent; border: none;"
        )
        badge.adjustSize()
        badge.move(
            max(0, field.width() - badge.width() - 8),
            max(0, (field.height() - badge.height()) // 2),
        )
        badge.show()
        badge.raise_()

        effect = QGraphicsOpacityEffect(badge)
        badge.setGraphicsEffect(effect)
        # Parenting the animation to the badge keeps it alive for the run without a self ref;
        # both are torn down together when the fade finishes.
        anim = QPropertyAnimation(effect, b"opacity", badge)
        anim.setDuration(900)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(lambda: self._end_flash(field, base_style, badge))
        anim.start()

    @staticmethod
    def _end_flash(field: QLabel, base_style: str, badge: QLabel) -> None:
        field.setStyleSheet(base_style)
        badge.deleteLater()
