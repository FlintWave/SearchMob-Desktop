"""`build_history_store` backend selection: persistent when possible, else in-memory."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from searchmob_desktop.data import history_factory
from searchmob_desktop.data.history import (
    InMemoryHistoryStore,
    SqlCipherHistoryStore,
)
from searchmob_desktop.prefs import UserPreferences


class _FakeMetaStore:
    def __init__(self, path: Path) -> None:
        self.path = path


class _FakeVault:
    """Minimal stand-in for an unlocked OS-keyring StorageBootstrap."""

    def __init__(self, tmp_path: Path) -> None:
        self.is_unlocked = True
        self.metadata_store = _FakeMetaStore(tmp_path / "vault.json")

    def dek_provider(self):  # type: ignore[no-untyped-def]
        return lambda: b"\x00" * 32


def _prefs(*, history: bool) -> UserPreferences:
    return dataclasses.replace(UserPreferences(), history_enabled=history)


def test_disabled_history_is_in_memory_and_off(monkeypatch: pytest.MonkeyPatch) -> None:
    store = history_factory.build_history_store(_prefs(history=False))
    assert isinstance(store, InMemoryHistoryStore)
    assert store.enabled is False


def test_enabled_without_vault_falls_back_to_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(history_factory, "sqlcipher_available", lambda: True)
    monkeypatch.setattr(history_factory, "open_os_vault", lambda *, create=False: None)
    store = history_factory.build_history_store(_prefs(history=True))
    assert isinstance(store, InMemoryHistoryStore)
    assert store.enabled is True  # still records, just not persisted


def test_enabled_without_sqlcipher_falls_back_to_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(history_factory, "sqlcipher_available", lambda: False)
    # open_os_vault must not even be consulted when sqlcipher is missing.
    monkeypatch.setattr(
        history_factory,
        "open_os_vault",
        lambda *, create=False: pytest.fail("vault opened despite missing sqlcipher"),
    )
    store = history_factory.build_history_store(_prefs(history=True))
    assert isinstance(store, InMemoryHistoryStore)
    assert store.enabled is True


def test_enabled_with_vault_and_sqlcipher_is_persistent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(history_factory, "sqlcipher_available", lambda: True)
    monkeypatch.setattr(
        history_factory, "open_os_vault", lambda *, create=False: _FakeVault(tmp_path)
    )
    store = history_factory.build_history_store(_prefs(history=True))
    assert isinstance(store, SqlCipherHistoryStore)
    assert store.enabled is True
