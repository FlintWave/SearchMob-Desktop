"""GUI: the in-app update banner surfaces from prefs, and the Settings window is 4:3-locked."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from searchmob_desktop.data.history import InMemoryHistoryStore
from searchmob_desktop.gui.main_window import MainWindow
from searchmob_desktop.gui.onboarding_dialog import ONBOARDING_VERSION
from searchmob_desktop.gui.settings_dialog import SettingsDialog
from searchmob_desktop.prefs import JsonPreferencesStore
from searchmob_desktop.update import VersionTag


def _newer_than_current() -> str:
    code = MainWindow._current_version_code()
    return VersionTag(code // 10000, (code // 100) % 100, (code % 100) + 1).formatted()


def _store_with_pending(tmp_path: Path, version: str) -> JsonPreferencesStore:
    store = JsonPreferencesStore(path=tmp_path / "prefs.json")
    store.save(
        replace(
            store.load(),
            # Mark onboarding done so constructing the window does not schedule a blocking wizard
            # (these tests assert on the update banner, not first-run).
            onboarding_completed=True,
            onboarding_version=ONBOARDING_VERSION,
            pending_update_version=version,
            pending_update_url="https://example.test/r/newer",
        )
    )
    return store


def test_recheck_timer_runs_while_window_stays_open(qapp: object, tmp_path: Path) -> None:
    # Regression: the update check used to run only once per launch, so a release published while
    # the app stayed open was never surfaced. Showing the window starts a RECURRING re-check timer.
    import time

    from searchmob_desktop.gui.main_window import _UPDATE_RECHECK_INTERVAL_MS

    store = JsonPreferencesStore(path=tmp_path / "prefs.json")
    store.save(
        replace(
            store.load(),
            onboarding_completed=True,
            onboarding_version=ONBOARDING_VERSION,
            # A fresh stamp keeps the launch tick throttled, so this test never touches the network.
            last_update_check_ms=int(time.time() * 1000),
        )
    )
    window = MainWindow(prefs_store=store, history_store=InMemoryHistoryStore())
    window.show()
    try:
        timer = window._update_recheck_timer
        assert timer.isActive()
        assert not timer.isSingleShot()
        assert timer.interval() == _UPDATE_RECHECK_INTERVAL_MS
    finally:
        window.close()


def test_banner_shown_when_prefs_has_newer_pending(qapp: object, tmp_path: Path) -> None:
    version = _newer_than_current()
    window = MainWindow(
        prefs_store=_store_with_pending(tmp_path, version),
        history_store=InMemoryHistoryStore(),
    )
    assert window._pending_update == (version, "https://example.test/r/newer")
    assert not window._update_banner.isHidden()
    assert f"SearchMob {version} is available." == window._update_label.text()


def test_banner_hidden_when_pending_not_newer(qapp: object, tmp_path: Path) -> None:
    code = MainWindow._current_version_code()
    same = VersionTag(code // 10000, (code // 100) % 100, code % 100).formatted()
    window = MainWindow(
        prefs_store=_store_with_pending(tmp_path, same),
        history_store=InMemoryHistoryStore(),
    )
    assert window._pending_update is None
    assert window._update_banner.isHidden()


def test_dismiss_hides_banner_for_session(qapp: object, tmp_path: Path) -> None:
    window = MainWindow(
        prefs_store=_store_with_pending(tmp_path, _newer_than_current()),
        history_store=InMemoryHistoryStore(),
    )
    assert not window._update_banner.isHidden()
    window._update_banner_dismiss()
    assert window._update_banner.isHidden()


def test_settings_window_locked_to_4_3(qapp: object, tmp_path: Path) -> None:
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent

    store = JsonPreferencesStore(path=tmp_path / "prefs.json")
    dialog = SettingsDialog(prefs_store=store, history_store=InMemoryHistoryStore())
    # Opens at 4:3.
    assert dialog.width() == 800
    assert dialog.height() == 600
    # A resize that breaks the ratio is snapped back: height tracks 3/4 of the width. Drive the
    # handler directly (no processEvents) so this stays hermetic in the shared-QApplication session.
    dialog.resize(1200, 1000)
    dialog.resizeEvent(QResizeEvent(QSize(1200, 1000), QSize(800, 600)))
    assert dialog.height() == round(dialog.width() * 3 / 4) == 900
