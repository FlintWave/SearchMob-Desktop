"""SettingsDialog interactions: each toggle/radio persists to a tmp JsonPreferencesStore.

The dialog writes through to `prefs.json` on every change, so each test drives the widget and then
reads `store.load()` back. The network toggle pops a warning modal; `QMessageBox.exec` is
monkeypatched so nothing blocks. No vault, network, or real config is touched (tmp prefs only).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QCheckBox, QMessageBox, QRadioButton

from searchmob_desktop.data.history import InMemoryHistoryStore
from searchmob_desktop.gui.settings_dialog import SettingsDialog
from searchmob_desktop.gui.theme import DARK, LIGHT, SYSTEM
from searchmob_desktop.prefs import JsonPreferencesStore


def _store(tmp_path: Path) -> JsonPreferencesStore:
    return JsonPreferencesStore(path=tmp_path / "prefs.json")


def _dialog(store: JsonPreferencesStore, **kwargs: object) -> SettingsDialog:
    return SettingsDialog(
        prefs_store=store,
        history_store=InMemoryHistoryStore(),
        **kwargs,  # type: ignore[arg-type]
    )


def _radio(dialog: SettingsDialog, label: str) -> QRadioButton:
    for radio in dialog.findChildren(QRadioButton):
        if radio.text() == label:
            return radio
    raise AssertionError(f"no radio labeled {label!r}")


def _checkbox_startswith(dialog: SettingsDialog, prefix: str) -> QCheckBox:
    for cb in dialog.findChildren(QCheckBox):
        if cb.text().startswith(prefix):
            return cb
    raise AssertionError(f"no checkbox starting with {prefix!r}")


def test_theme_radio_saves_pref_and_emits(qapp: object, tmp_path: Path) -> None:
    store = _store(tmp_path)
    dialog = _dialog(store)
    emitted: list[str] = []
    dialog.themeChanged.connect(emitted.append)

    _radio(dialog, "Dark").setChecked(True)
    assert store.load().theme == DARK
    assert emitted[-1] == DARK

    _radio(dialog, "Light").setChecked(True)
    assert store.load().theme == LIGHT
    assert emitted[-1] == LIGHT

    _radio(dialog, "Follow system").setChecked(True)
    assert store.load().theme == SYSTEM
    assert emitted[-1] == SYSTEM


def test_engine_toggle_persists_engine_enabled(qapp: object, tmp_path: Path) -> None:
    store = _store(tmp_path)
    dialog = _dialog(store)
    ddg = _checkbox_startswith(dialog, "DuckDuckGo")

    # Default-on; turning it off must persist engine_enabled["duckduckgo"] = False.
    ddg.setChecked(False)
    assert store.load().engine_enabled.get("duckduckgo") is False

    ddg.setChecked(True)
    assert store.load().engine_enabled.get("duckduckgo") is True


def test_suggestions_toggle_persists(qapp: object, tmp_path: Path) -> None:
    store = _store(tmp_path)
    dialog = _dialog(store)
    cb = _checkbox_startswith(dialog, "Live suggestions")

    cb.setChecked(True)
    assert store.load().upstream_suggestions_enabled is True
    cb.setChecked(False)
    assert store.load().upstream_suggestions_enabled is False


def test_update_check_toggle_persists(qapp: object, tmp_path: Path) -> None:
    store = _store(tmp_path)
    dialog = _dialog(store)
    cb = _checkbox_startswith(dialog, "Check for updates")

    # On by default; turning it off then on must round-trip.
    cb.setChecked(False)
    assert store.load().update_check_enabled is False
    cb.setChecked(True)
    assert store.load().update_check_enabled is True


class _FakeController:
    """Captures the host the dialog asks the (would-be) running server to bind to."""

    def __init__(self) -> None:
        self.hosts: list[str] = []

    def set_host(self, host: str) -> None:
        self.hosts.append(host)


def test_network_toggle_on_confirmed_enables_and_sets_host(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    store = _store(tmp_path)
    controller = _FakeController()
    dialog = _dialog(store, server_controller=controller)
    cb = _checkbox_startswith(dialog, "Allow access from your network")

    cb.setChecked(True)
    assert store.load().network_access_enabled is True
    assert controller.hosts == ["0.0.0.0"]


def test_network_toggle_on_cancelled_stays_off_and_snaps_back(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel)
    store = _store(tmp_path)
    controller = _FakeController()
    dialog = _dialog(store, server_controller=controller)
    cb = _checkbox_startswith(dialog, "Allow access from your network")

    cb.setChecked(True)
    assert store.load().network_access_enabled is False
    assert cb.isChecked() is False
    assert controller.hosts == []


def test_network_toggle_on_mints_token_and_reuses_it(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    store = _store(tmp_path)
    dialog = _dialog(store, server_controller=_FakeController())
    cb = _checkbox_startswith(dialog, "Allow access from your network")

    cb.setChecked(True)
    token = store.load().network_access_token
    assert token  # a non-empty token was minted on first enable
    assert len(token) >= 24

    # Turning off keeps the token so re-enabling reuses it (stable browser setup URLs).
    cb.setChecked(False)
    assert store.load().network_access_token == token
    cb.setChecked(True)
    assert store.load().network_access_token == token


def test_local_ai_picking_a_model_enables_and_persists(qapp: object, tmp_path: Path) -> None:
    from searchmob_desktop.engines.local_llm import LlmBackend

    store = _store(tmp_path)
    dialog = _dialog(store)
    assert store.load().llm_enabled is False
    dialog._on_models_detected(
        [LlmBackend("Ollama", "http://127.0.0.1:11434/v1", ("llama3", "qwen2"))]
    )
    # "Off" plus the two detected models.
    assert dialog._llm_combo.count() == 3
    # Detection alone does not enable: the feature was off, so it stays on "Off".
    assert store.load().llm_enabled is False
    # Selecting a model turns the box on and persists the choice.
    idx = dialog._llm_combo.findText("Ollama — qwen2")
    assert idx > 0
    dialog._llm_combo.setCurrentIndex(idx)
    assert store.load().llm_enabled is True
    assert store.load().llm_model == "qwen2"
    # Selecting "Off" turns it back off.
    dialog._llm_combo.setCurrentIndex(0)
    assert store.load().llm_enabled is False


def test_local_ai_saved_enabled_model_is_preselected(qapp: object, tmp_path: Path) -> None:
    from dataclasses import replace

    from searchmob_desktop.engines.local_llm import LlmBackend

    store = _store(tmp_path)
    store.save(
        replace(
            store.load(),
            llm_enabled=True,
            llm_base_url="http://127.0.0.1:11434/v1",
            llm_model="llama3",
        )
    )
    dialog = _dialog(store)
    dialog._on_models_detected(
        [LlmBackend("Ollama", "http://127.0.0.1:11434/v1", ("llama3", "qwen2"))]
    )
    # The saved, enabled model is the current selection (not "Off").
    assert dialog._llm_combo.currentText() == "Ollama — llama3"


def test_local_ai_no_models_shows_only_off(qapp: object, tmp_path: Path) -> None:
    store = _store(tmp_path)
    dialog = _dialog(store)
    dialog._on_models_detected([])
    # Just the "Off" entry; the feature stays off.
    assert dialog._llm_combo.count() == 1
    assert dialog._llm_combo.currentText().startswith("Off")
    assert store.load().llm_enabled is False
