"""Qt glue for live UI-language switching.

The pure i18n catalog (`searchmob_desktop.i18n`) holds the active locale and a plain-callable
subscriber list. This module bridges that to Qt: a `QObject` re-emits a `languageChanged` signal
time the locale changes, so persistent windows reconnect a `retranslate()` slot and re-pull their
`tr(...)` text live, and `apply_language` also flips the application layout direction for the
right-to-left locales (Arabic, Urdu). Transient dialogs need no slot: they read `tr(...)` at
construction and so open in whatever language is active.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from searchmob_desktop.i18n import (
    is_rtl,
    normalize_tag,
    resolve_os_locale,
    set_active_locale,
    subscribe,
)


class _LanguageBridge(QObject):
    """Re-emits the catalog's locale changes as a Qt signal (the new BCP-47 tag)."""

    languageChanged = Signal(str)


_bridge: _LanguageBridge | None = None


def language_bridge() -> _LanguageBridge:
    """The process-wide language bridge, created (and subscribed to the catalog) on first use."""
    global _bridge
    if _bridge is None:
        bridge = _LanguageBridge()
        subscribe(bridge.languageChanged.emit)
        _bridge = bridge
    return _bridge


def apply_language(app: QApplication, tag: str) -> str:
    """Set the active UI locale and the app's layout direction (rtl for Arabic/Urdu). Returns it.

    Setting the locale notifies subscribers, so the bridge fires `languageChanged` and every
    connected window retranslates. Returns the normalized tag actually applied.
    """
    language_bridge()  # ensure the bridge is subscribed before the locale change fires
    new_tag = set_active_locale(tag)
    rtl = is_rtl(new_tag)
    app.setLayoutDirection(
        Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight
    )
    return new_tag


def initial_locale(prefs_language: str) -> str:
    """The locale to start in: the saved language if set, else the OS locale (else English)."""
    return normalize_tag(prefs_language) if prefs_language else resolve_os_locale()
