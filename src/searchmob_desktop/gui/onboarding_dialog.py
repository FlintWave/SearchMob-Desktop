"""First-run setup wizard, the desktop analogue of the Android `OnboardingWizard`.

Shown once on first launch (gated by `prefs.onboarding_completed`): a small, skippable pager over
Welcome, Privacy, Browser setup, and - only where a per-user background service is available - a
Background service page. It is OS-aware: the service page is omitted on platforms without one, and
its copy names the platform's actual mechanism, so a user only sees guidance that applies to them.
Skip and Finish both persist the completed flag so the wizard never reappears.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtGui import QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from searchmob_desktop import service
from searchmob_desktop.gui.browser_setup_dialog import BrowserSetupDialog, choose_setup_host
from searchmob_desktop.gui.server_controller import LocalServerController
from searchmob_desktop.prefs import JsonPreferencesStore
from searchmob_desktop.server import local_hostnames

# Bump this when the wizard gains a step worth re-showing to existing users (e.g. a new opt-in
# feature). The wizard re-appears once for anyone whose saved `onboarding_version` is below this.
# 1: added the click-personalization step.
ONBOARDING_VERSION = 1


class OnboardingDialog(QDialog):
    """The first-run wizard. Owns no state beyond the prefs flag it sets on completion."""

    def __init__(
        self,
        prefs_store: JsonPreferencesStore,
        server_controller: LocalServerController | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._prefs_store = prefs_store
        self._server_controller = server_controller
        self._prefs = prefs_store.load()
        # A returning user (already onboarded once) is re-shown the wizard after an update only to
        # surface the new opt-in feature, so they get just that page, not the whole setup again.
        self._returning = self._prefs.onboarding_completed

        self.setWindowTitle(
            "What's new in SearchMob" if self._returning else "Welcome to SearchMob"
        )
        self.setModal(True)
        self.resize(640, 560)

        outer = QVBoxLayout(self)

        top = QHBoxLayout()
        brand = QLabel("SearchMob")
        brand_font = brand.font()
        brand_font.setBold(True)
        brand.setFont(brand_font)
        top.addWidget(brand)
        top.addStretch(1)
        skip = QPushButton("Skip")
        skip.clicked.connect(self._finish)
        top.addWidget(skip)
        outer.addLayout(top)

        # Build the page list. A returning user (re-onboarded after an update) sees only the new
        # feature; a first-run user gets the full setup with the personalization opt-in as the last
        # step (not an early interruption). The service page is included only where supported.
        self._stack = QStackedWidget(self)
        if self._returning:
            self._stack.addWidget(self._personalize_page())
        else:
            self._stack.addWidget(self._welcome_page())
            self._stack.addWidget(self._privacy_page())
            self._stack.addWidget(self._browser_page())
            if service.is_supported():
                self._stack.addWidget(self._service_page())
            self._stack.addWidget(self._personalize_page())
        outer.addWidget(self._stack, stretch=1)

        nav = QHBoxLayout()
        self._back_btn = QPushButton("Back")
        self._back_btn.clicked.connect(self._back)
        self._next_btn = QPushButton("Next")
        self._next_btn.clicked.connect(self._next)
        nav.addWidget(self._back_btn)
        nav.addStretch(1)
        nav.addWidget(self._next_btn)
        outer.addLayout(nav)

        self._stack.currentChanged.connect(lambda _i: self._update_nav())
        self._update_nav()
        self._centered = False

    def showEvent(self, event: QShowEvent) -> None:
        """Center the wizard over the main window on first show.

        A parented modal is not reliably centered by every window manager (it can open in a corner),
        so we position it explicitly the first time it appears: over the parent's frame when the
        parent is actually on screen, otherwise over the active screen as a fallback (the parent may
        not be mapped yet when the wizard is shown right after launch).
        """
        super().showEvent(event)
        if self._centered:
            return
        self._centered = True
        geo = self.frameGeometry()
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            geo.moveCenter(parent.frameGeometry().center())
        else:
            screen = self.screen() or QGuiApplication.primaryScreen()
            if screen is None:
                return
            geo.moveCenter(screen.availableGeometry().center())
        self.move(geo.topLeft())

    # --- Page builders -----------------------------------------------------------------------

    @staticmethod
    def _page(heading: str, body: str, extra: QWidget | None = None) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel(heading)
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 4)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        text = QLabel(body)
        text.setWordWrap(True)
        layout.addWidget(text)
        if extra is not None:
            layout.addWidget(extra)
        layout.addStretch(1)
        return page

    def _welcome_page(self) -> QWidget:
        return self._page(
            "Welcome to SearchMob",
            "Private, on-device metasearch. Your searches are aggregated from several engines "
            "behind one box, with no tracking and no account. Let's set up a couple of things so "
            "you can search straight from your browser.",
        )

    def _privacy_page(self) -> QWidget:
        return self._page(
            "Private by default",
            "SearchMob stores nothing by default. There are no cookies, no referrer, and no "
            "device identifier, and the only outbound traffic is the searches you run plus an "
            "optional once-a-day update check you can turn off. You can optionally enable "
            "encrypted, zero-knowledge search history later in Settings.",
        )

    def _personalize_page(self) -> QWidget:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        col = QVBoxLayout(box)
        self._personalize_check = QCheckBox("Turn on personalized ranking (recommended)")
        self._personalize_check.setChecked(self._prefs.personalization_enabled)
        self._personalize_check.toggled.connect(self._on_personalize_toggled)
        col.addWidget(self._personalize_check)
        note = QLabel(
            "It is as private as your data and device are: keep a strong vault passphrase and a "
            "locked, encrypted device, and turn on zero-knowledge mode for the strongest "
            "protection. You can reset or export it any time in Settings."
        )
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        col.addWidget(note)
        return self._page(
            "Personalize your ranking (recommended)",
            "SearchMob can learn which sites you click and quietly move the ones you prefer "
            "higher. It gets better the more you search. Everything stays on this device: what it "
            "learns is encrypted with your vault key, is never sent anywhere, and other people on "
            "your network can never read it or change it.",
            extra=box,
        )

    def _browser_page(self) -> QWidget:
        btn = QPushButton("Open browser setup")
        btn.clicked.connect(self._open_browser_setup)
        page = self._page(
            "Make SearchMob your search engine",
            "Add SearchMob to your browser so address-bar searches go through your private local "
            "server. Start the local server from the main window first, then open the setup guide "
            "for step-by-step instructions for your browser.",
            extra=btn,
        )
        return page

    def _service_page(self) -> QWidget:
        mechanism = service.mechanism_label() or "a background service"
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        col = QVBoxLayout(box)
        self._service_status = QLabel(service.status().summary())
        self._service_status.setWordWrap(True)
        self._service_status.setProperty("role", "muted")
        col.addWidget(self._service_status)
        self._service_btn = QPushButton("Install and start")
        self._service_btn.clicked.connect(self._install_service)
        col.addWidget(self._service_btn)
        if service.status().installed:
            self._service_btn.setText("Reinstall")
        return self._page(
            "Run in the background (optional)",
            f"Optionally run the local server as {mechanism} so your browser can use SearchMob "
            "even when this window is closed. The app still opens normally; this is opt-in and you "
            "can remove it any time from Settings.",
            extra=box,
        )

    # --- Actions -----------------------------------------------------------------------------

    def _open_browser_setup(self) -> None:
        running = self._server_controller is not None and self._server_controller.is_running
        port: int | None = 8787 if running else None
        host = choose_setup_host(
            network_enabled=self._prefs.network_access_enabled,
            configured_hostnames=self._prefs.network_hostnames,
            local_names=sorted(local_hostnames()),
        )
        token = (
            self._prefs.network_access_token or None
            if (self._prefs.network_access_enabled and self._prefs.network_access_token)
            else None
        )
        BrowserSetupDialog(host=host, port=port, parent=self, token=token).exec()

    def _on_personalize_toggled(self, checked: bool) -> None:
        # Persist immediately (like the other opt-ins) so nothing is recorded unless the box is on.
        try:
            self._prefs_store.save(
                replace(self._prefs_store.load(), personalization_enabled=checked)
            )
        except OSError:
            pass  # Non-fatal: the Settings toggle offers another chance to enable it.

    def _install_service(self) -> None:
        host = "0.0.0.0" if self._prefs.network_access_enabled else "127.0.0.1"
        ok, message = service.install_and_enable(host=host)
        if not ok:
            QMessageBox.warning(self, "Could not install the service", message)
        self._service_status.setText(service.status().summary())
        if service.status().installed:
            self._service_btn.setText("Reinstall")

    # --- Navigation --------------------------------------------------------------------------

    def _update_nav(self) -> None:
        idx = self._stack.currentIndex()
        self._back_btn.setEnabled(idx > 0)
        self._next_btn.setText("Finish" if idx == self._stack.count() - 1 else "Next")

    def _back(self) -> None:
        self._stack.setCurrentIndex(max(0, self._stack.currentIndex() - 1))

    def _next(self) -> None:
        idx = self._stack.currentIndex()
        if idx >= self._stack.count() - 1:
            self._finish()
        else:
            self._stack.setCurrentIndex(idx + 1)

    def _finish(self) -> None:
        try:
            self._prefs_store.save(
                replace(
                    self._prefs_store.load(),
                    onboarding_completed=True,
                    onboarding_version=ONBOARDING_VERSION,
                )
            )
        except OSError:
            pass  # Non-fatal: worst case the wizard shows again next launch.
        self.accept()
