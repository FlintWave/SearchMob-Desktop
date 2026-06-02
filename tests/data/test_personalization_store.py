"""Personalization-model persistence: vault round-trip and fail-soft when no vault is available."""

from __future__ import annotations

import pytest

from searchmob_desktop.data import personalization_store as store
from searchmob_desktop.engines.rank import personalize as p


class _FakePrefs:
    """In-memory stand-in for EncryptedPreferences (get/put over a dict)."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def put(self, key: str, value: str) -> None:
        self._data[key] = value


def _trained() -> p.PersonalizationModel:
    m = p.PersonalizationModel()
    now = 20000 * 86_400_000
    for _ in range(6):
        p.update_from_click(m, ["a.com", "so.com"], 1, p.query_terms("python"), now)
    return m


def test_save_then_load_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakePrefs()
    monkeypatch.setattr(store, "open_encrypted_prefs", lambda: fake)

    model = _trained()
    assert store.save_personalization(model) is True
    assert store.PERSONALIZATION_KEY in fake._data

    loaded = store.load_personalization()
    assert loaded.total_clicked_queries == model.total_clicked_queries
    assert "so.com" in loaded.domains


def test_load_returns_empty_without_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "open_encrypted_prefs", lambda: None)
    assert store.load_personalization().is_empty()


def test_save_reports_failure_without_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "open_encrypted_prefs", lambda: None)
    assert store.save_personalization(_trained()) is False


def test_load_empty_blob_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "open_encrypted_prefs", lambda: _FakePrefs())
    assert store.load_personalization().is_empty()
