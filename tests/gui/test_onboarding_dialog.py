"""First-run wizard: page composition (OS-aware), navigation, and the completed flag.

Offscreen Qt only. The background-service page is platform-dependent, so the OS-awareness tests
force `service.is_supported` both ways rather than depending on the host.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from pathlib import Path

from searchmob_desktop import service
from searchmob_desktop.gui.onboarding_dialog import OnboardingDialog
from searchmob_desktop.prefs import JsonPreferencesStore


def _store(tmp_path: Path) -> JsonPreferencesStore:
    return JsonPreferencesStore(tmp_path / "prefs.json")


def test_service_page_present_only_when_supported(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "is_supported", lambda: False)
    without = OnboardingDialog(prefs_store=_store(tmp_path))
    assert without._stack.count() == 3  # Welcome, Privacy, Browser

    monkeypatch.setattr(service, "is_supported", lambda: True)
    monkeypatch.setattr(service, "mechanism_label", lambda: "a systemd user service")
    monkeypatch.setattr(service, "status", lambda: service.ServiceStatus(True, False, False, False))
    with_service = OnboardingDialog(prefs_store=_store(tmp_path))
    assert with_service._stack.count() == 4  # + Background service


def test_finish_persists_completed_flag(qapp: object, tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.load().onboarding_completed is False
    dialog = OnboardingDialog(prefs_store=store)
    dialog._finish()
    assert store.load().onboarding_completed is True


def test_skip_also_persists_completed_flag(qapp: object, tmp_path: Path) -> None:
    # Skip is wired to the same _finish handler; a skipped wizard must not reappear.
    store = _store(tmp_path)
    dialog = OnboardingDialog(prefs_store=store)
    dialog._finish()
    assert store.load().onboarding_completed is True


def test_navigation_back_next_and_finish_label(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "is_supported", lambda: False)
    dialog = OnboardingDialog(prefs_store=_store(tmp_path))
    assert dialog._stack.currentIndex() == 0
    assert not dialog._back_btn.isEnabled()
    assert dialog._next_btn.text() == "Next"

    dialog._next()
    assert dialog._stack.currentIndex() == 1
    assert dialog._back_btn.isEnabled()

    dialog._back()
    assert dialog._stack.currentIndex() == 0

    # Walk to the last page; Next becomes Finish.
    while dialog._stack.currentIndex() < dialog._stack.count() - 1:
        dialog._next()
    assert dialog._next_btn.text() == "Finish"
