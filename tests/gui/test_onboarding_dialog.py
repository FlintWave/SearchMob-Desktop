"""First-run wizard: page composition (OS-aware), navigation, and the completed flag.

Offscreen Qt only. The background-service page is platform-dependent, so the OS-awareness tests
force `service.is_supported` both ways rather than depending on the host.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from pathlib import Path

from searchmob_desktop import service
from searchmob_desktop.gui.onboarding_dialog import ONBOARDING_VERSION, OnboardingDialog
from searchmob_desktop.prefs import JsonPreferencesStore


def _store(tmp_path: Path) -> JsonPreferencesStore:
    return JsonPreferencesStore(tmp_path / "prefs.json")


def test_service_page_present_only_when_supported(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "is_supported", lambda: False)
    without = OnboardingDialog(prefs_store=_store(tmp_path))
    assert without._stack.count() == 4  # Welcome, Privacy, Personalize, Browser

    monkeypatch.setattr(service, "is_supported", lambda: True)
    monkeypatch.setattr(service, "mechanism_label", lambda: "a systemd user service")
    monkeypatch.setattr(service, "status", lambda: service.ServiceStatus(True, False, False, False))
    with_service = OnboardingDialog(prefs_store=_store(tmp_path))
    assert with_service._stack.count() == 5  # + Background service


def test_finish_persists_completed_flag(qapp: object, tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.load().onboarding_completed is False
    dialog = OnboardingDialog(prefs_store=store)
    dialog._finish()
    assert store.load().onboarding_completed is True


def test_finish_stamps_onboarding_version(qapp: object, tmp_path: Path) -> None:
    # Finishing records the revision so the wizard does not re-appear until a future bump.
    store = _store(tmp_path)
    assert store.load().onboarding_version == 0
    OnboardingDialog(prefs_store=store)._finish()
    assert store.load().onboarding_version == ONBOARDING_VERSION


def test_personalize_page_toggle_persists_immediately(qapp: object, tmp_path: Path) -> None:
    # The personalization opt-in writes through on toggle, so nothing is recorded unless it is on.
    store = _store(tmp_path)
    dialog = OnboardingDialog(prefs_store=store)
    assert store.load().personalization_enabled is False
    dialog._personalize_check.setChecked(True)
    assert store.load().personalization_enabled is True


def test_returning_user_sees_only_the_new_feature_page(qapp: object, tmp_path: Path) -> None:
    # A re-onboarded user (already completed onboarding before the version bump) gets just the
    # personalization page so they can activate the new feature, not the whole first-run setup.
    from dataclasses import replace

    store = _store(tmp_path)
    store.save(replace(store.load(), onboarding_completed=True))
    dialog = OnboardingDialog(prefs_store=store)
    assert dialog._stack.count() == 1
    # The single page carries the activation toggle (so they can turn the feature on).
    assert dialog._personalize_check is not None
    dialog._personalize_check.setChecked(True)
    assert store.load().personalization_enabled is True


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
