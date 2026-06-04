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

    from searchmob_desktop.gui.language import apply_language, initial_locale
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
    # Apply the UI language before building any widget so the first paint is already localized (and
    # the layout direction is set for right-to-left languages). Empty pref => follow the OS locale.
    apply_language(app, initial_locale(prefs.language))  # type: ignore[arg-type]
    apply_theme(
        app,  # type: ignore[arg-type]
        prefs.theme,
        prefs.light_theme,
        prefs.dark_theme,
        prefs.font_point_size,
    )

    window = MainWindow(prefs_store=prefs_store)
    window.show()
    # Start the local server on launch so SearchMob is immediately reachable (and usable as the
    # browser's search engine) without the user starting it by hand. Fail-soft: a bind error is
    # reported through the window's serverError handler, not raised here.
    window.start_server()
    return int(app.exec())
