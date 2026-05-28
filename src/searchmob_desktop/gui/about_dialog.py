"""About / Privacy dialog, mirroring the Android `AboutScreen`.

Same sections, same wording: what SearchMob is, the no-data block, the protection methodology,
the tips list, the caveat in error color, and the version / license / copyright footer with
buttons to the public repo and the bug tracker.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from searchmob_desktop.version import __version__

REPO_URL = "https://github.com/FlintWave/SearchMob-Desktop"
BUG_URL = "https://github.com/FlintWave/SearchMob-Desktop/issues/new/choose"


class AboutDialog(QDialog):
    """Stateless about / privacy dialog. No prefs, no IO."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About SearchMob Desktop")
        self.setModal(True)
        self.resize(640, 720)

        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        host = QWidget(scroll)
        layout = QVBoxLayout(host)
        layout.setSpacing(14)

        self._add_section(
            layout,
            title="What SearchMob is",
            body=(
                "SearchMob Desktop is a private, on-device metasearch app. It runs a small "
                "local HTTP server on your computer and queries public search engines directly "
                "on your behalf. There are no SearchMob servers, so your searches never pass "
                "through any service we operate."
            ),
        )
        self._add_section(
            layout,
            title="We never receive your data",
            body=(
                "SearchMob sends nothing back to its developers. The only outbound traffic is "
                "the searches you run, plus an optional once-a-day update check to GitHub that "
                "you can turn off in Settings."
            ),
            bullets=(
                "No telemetry, no analytics, and no crash or diagnostic reporting.",
                "No accounts to sign in to and no advertising IDs.",
                "No device identifiers.",
                "No background phone-home: the app makes no outbound calls except searches "
                "and the optional update check, both routed through the privacy proxy.",
            ),
        )
        self._add_section(
            layout,
            title="How it protects you when you search",
            body=(
                "SearchMob acts as a privacy proxy to the upstream engines. Requests carry no "
                "cookies, no referrer, and no user or device identifier, and the User-Agent is "
                "rotated on each request. It never scrapes Google.\n\n"
                "Search history is off by default. If you turn it on, it stays local to your "
                "computer, is encrypted at rest, and you can purge it at any time. An optional "
                "zero-knowledge passphrase mode means even a copy of the database is useless "
                "without your passphrase."
            ),
        )
        self._add_section(
            layout,
            title="Tips to keep searches more private",
            bullets=(
                "Keep history off, or use the zero-knowledge passphrase mode if you want it on.",
                "Avoid queries that contain your real name, address, or account details.",
                "Remember that bring-your-own API keys tie those queries to your account at "
                "that provider.",
                "Use a trustworthy VPN or Tor if you want to hide your IP from the upstream "
                "engines.",
                "Clear your history periodically.",
            ),
        )

        # Caveat block in error color.
        caveat = QFrame(host)
        caveat.setProperty("role", "caveat")
        caveat.setFrameShape(QFrame.Shape.StyledPanel)
        caveat_layout = QVBoxLayout(caveat)
        caveat_title = QLabel("A caveat")
        caveat_title.setProperty("role", "caveat-text")
        title_font = caveat_title.font()
        title_font.setBold(True)
        caveat_title.setFont(title_font)
        caveat_body = QLabel(
            "True anonymity on today's internet is effectively impossible. Upstream search "
            "engines and the networks in between can still observe request metadata (your IP "
            "address, timing, and query patterns) and may correlate that activity. SearchMob "
            "minimizes what it, and especially its developers, can see, but it cannot make "
            "you anonymous to the wider internet. Be skeptical of anything that promises "
            "total anonymity."
        )
        caveat_body.setProperty("role", "caveat-text")
        caveat_body.setWordWrap(True)
        caveat_layout.addWidget(caveat_title)
        caveat_layout.addWidget(caveat_body)
        layout.addWidget(caveat)

        # Footer: version, license, copyright, attribution, buttons.
        version_label = QLabel(f"Version {__version__}")
        version_label.setProperty("role", "muted")
        license_label = QLabel("License: AGPL-3.0-or-later")
        license_label.setProperty("role", "muted")
        copyright_label = QLabel("Copyright © 2026 FlintWave. Contact: flintwave@tuta.com")
        copyright_label.setProperty("role", "muted")
        attribution_label = QLabel("Search icons created by Freepik - Flaticon")
        attribution_label.setProperty("role", "muted")
        attribution_label.setWordWrap(True)
        layout.addWidget(version_label)
        layout.addWidget(license_label)
        layout.addWidget(copyright_label)
        layout.addWidget(attribution_label)

        buttons = QHBoxLayout()
        repo_btn = QPushButton("View source on GitHub")
        repo_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        bug_btn = QPushButton("Report a bug")
        bug_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(BUG_URL)))
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(repo_btn)
        buttons.addWidget(bug_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        scroll.setWidget(host)
        outer.addWidget(scroll)

    @staticmethod
    def _add_section(
        layout: QVBoxLayout,
        *,
        title: str,
        body: str = "",
        bullets: tuple[str, ...] = (),
    ) -> None:
        title_label = QLabel(title)
        title_font = title_label.font()
        title_font.setBold(True)
        title_font.setPointSizeF(title_font.pointSizeF() + 1.5)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        if body:
            body_label = QLabel(body)
            body_label.setWordWrap(True)
            layout.addWidget(body_label)
        for bullet in bullets:
            bullet_label = QLabel("•  " + bullet)
            bullet_label.setWordWrap(True)
            layout.addWidget(bullet_label)
