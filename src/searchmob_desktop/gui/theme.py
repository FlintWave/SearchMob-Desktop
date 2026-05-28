"""Theme helpers for the PySide6 shell.

The Android app gets Material You for free. On desktop we keep this small: light and dark QSS
stylesheets plus a `system` mode that picks the platform palette without forcing colors. The pure
helpers (`resolve_theme`, `theme_stylesheet`) are import-safe (no PySide6 import), so headless
tests can exercise them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

LIGHT = "light"
DARK = "dark"
SYSTEM = "system"

_VALID = frozenset({LIGHT, DARK, SYSTEM})

# Both QSS blocks are intentionally minimal. We want the native control look on each platform,
# only tweaking the surface color, the muted text color, and the result-row hover. Anything more
# elaborate fights Qt's native styling and looks worse on macOS in particular.

_LIGHT_QSS = """
QWidget { background-color: #fafafa; color: #1c1c1e; }
QMainWindow, QDialog { background-color: #fafafa; }
QStatusBar { background-color: #ececec; color: #444; }
QLineEdit {
    background-color: #ffffff;
    border: 1px solid #c8c8cc;
    border-radius: 6px;
    padding: 6px;
}
QPushButton { padding: 6px 12px; }
QListView, QTreeView { background-color: #ffffff; border: 1px solid #d4d4d8; }
QListView::item:hover, QTreeView::item:hover { background-color: #e8eefc; }
QFrame[role="caveat"] {
    background-color: #fde2e2;
    border: 1px solid #f5b5b5;
    border-radius: 6px;
}
QLabel[role="muted"] { color: #6e6e73; }
QLabel[role="url"] { color: #3060a8; }
QLabel[role="engine"] { color: #2a7a2a; }
QLabel[role="caveat-text"] { color: #8a1f1f; }
"""

_DARK_QSS = """
QWidget { background-color: #1c1c1e; color: #ececec; }
QMainWindow, QDialog { background-color: #1c1c1e; }
QStatusBar { background-color: #2a2a2c; color: #c8c8c8; }
QLineEdit {
    background-color: #2a2a2c;
    border: 1px solid #444;
    border-radius: 6px;
    padding: 6px;
    color: #ececec;
}
QPushButton { padding: 6px 12px; }
QListView, QTreeView { background-color: #232325; border: 1px solid #444; color: #ececec; }
QListView::item:hover, QTreeView::item:hover { background-color: #34384a; }
QFrame[role="caveat"] {
    background-color: #4a1f1f;
    border: 1px solid #7a3a3a;
    border-radius: 6px;
}
QLabel[role="muted"] { color: #a8a8ad; }
QLabel[role="url"] { color: #7ab0ff; }
QLabel[role="engine"] { color: #7adf7a; }
QLabel[role="caveat-text"] { color: #ffb0b0; }
"""


def resolve_theme(name: str | None) -> str:
    """Map a stored preference string to one of `LIGHT`, `DARK`, `SYSTEM`.

    Unknown / `None` falls through to `SYSTEM` so an old `prefs.json` written by a future build
    never crashes the launcher.
    """
    if name is None:
        return SYSTEM
    candidate = name.strip().lower()
    if candidate in _VALID:
        return candidate
    return SYSTEM


def theme_stylesheet(name: str) -> str:
    """Return the QSS for `name`. `SYSTEM` returns an empty string (no override)."""
    resolved = resolve_theme(name)
    if resolved == LIGHT:
        return _LIGHT_QSS
    if resolved == DARK:
        return _DARK_QSS
    return ""


def apply_theme(app: QApplication, theme: str) -> None:
    """Apply the theme stylesheet to `app`. No-op for `SYSTEM`."""
    app.setStyleSheet(theme_stylesheet(theme))
