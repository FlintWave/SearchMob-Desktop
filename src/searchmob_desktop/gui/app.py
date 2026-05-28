"""GUI entry point. `run_gui()` builds a `QApplication`, applies the theme, runs the event loop.

Imports of `PySide6` are deferred to `run_gui()` so a headless caller can import the GUI module
without paying for Qt initialization. This is what the CLI's `gui` subcommand calls into.
"""

from __future__ import annotations

import sys

from searchmob_desktop.prefs import JsonPreferencesStore


def run_gui(argv: list[str] | None = None) -> int:
    """Launch the GUI event loop.

    Returns the `QApplication.exec` exit code so callers can `sys.exit(run_gui())`.
    """
    # Defer the PySide6 import so `import searchmob_desktop.gui` is cheap and headless-safe.
    from PySide6.QtWidgets import QApplication

    from searchmob_desktop.gui.main_window import MainWindow
    from searchmob_desktop.gui.theme import apply_theme

    args = list(sys.argv if argv is None else argv)
    # `QApplication` mutates its argv; pass a copy so we do not surprise the caller.
    app = QApplication.instance()
    if app is None:
        app = QApplication(args)
    # If there is already a running QApplication (e.g. tests), reuse it but still apply theme.
    prefs_store = JsonPreferencesStore()
    prefs = prefs_store.load()
    apply_theme(app, prefs.theme)  # type: ignore[arg-type]

    window = MainWindow(prefs_store=prefs_store)
    window.show()
    return int(app.exec())
