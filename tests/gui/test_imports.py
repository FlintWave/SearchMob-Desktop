"""Module-level smoke test for the PySide6 GUI shell.

CI without a display cannot spin a `QApplication`; we only verify every module imports cleanly
and the public `run_gui` is callable. If `PySide6` is not installed (no `gui` extra), the whole
file is skipped, which matches the optional-dependency story in pyproject.
"""

from __future__ import annotations

import importlib

import pytest

pytest.importorskip("PySide6")


def test_gui_modules_import() -> None:
    """Each module loads without instantiating a QApplication."""
    modules = (
        "searchmob_desktop.gui",
        "searchmob_desktop.gui.app",
        "searchmob_desktop.gui.about_dialog",
        "searchmob_desktop.gui.browser_setup_dialog",
        "searchmob_desktop.gui.engines_catalog",
        "searchmob_desktop.gui.main_window",
        "searchmob_desktop.gui.results_view",
        "searchmob_desktop.gui.server_controller",
        "searchmob_desktop.gui.settings_dialog",
        "searchmob_desktop.gui.theme",
        "searchmob_desktop.gui.workers",
    )
    for name in modules:
        importlib.import_module(name)


def test_run_gui_is_callable() -> None:
    from searchmob_desktop.gui import run_gui

    assert callable(run_gui)
