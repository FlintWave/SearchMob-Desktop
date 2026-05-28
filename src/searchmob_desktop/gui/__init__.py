"""PySide6 desktop GUI shell for SearchMob Desktop.

The CLI's `gui` subcommand delegates here. The module is import-safe without a display: every
PySide6 import happens inside the entry-point functions so headless test runners can `import
searchmob_desktop.gui` without spinning up a `QApplication`.
"""

from __future__ import annotations

from searchmob_desktop.gui.app import run_gui

__all__ = ["run_gui"]
