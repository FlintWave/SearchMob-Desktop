"""Shared GUI test setup.

Force Qt's offscreen platform before any `QApplication` is created so widget tests run on headless
CI (which has no display). The `qapp` fixture hands out a single process-wide application instance.
"""

from __future__ import annotations

import os

import pytest

# Must be set before the first QApplication is constructed anywhere in the process.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp() -> object:
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
