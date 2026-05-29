"""Unit tests for the persistent settings store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from searchmob_desktop.prefs import JsonPreferencesStore, UserPreferences


def test_defaults_match_android_contract() -> None:
    """Store-nothing default + update-check opt-out (default on)."""
    prefs = UserPreferences()
    assert prefs.theme == "system"
    assert prefs.history_enabled is False
    assert prefs.network_access_enabled is False
    assert prefs.upstream_suggestions_enabled is False
    assert prefs.update_check_enabled is True
    assert prefs.last_update_check_ms == 0
    assert prefs.network_access_token == ""
    assert dict(prefs.engine_enabled) == {}


def test_round_trip_through_json(tmp_path: Path) -> None:
    path = tmp_path / "prefs.json"
    store = JsonPreferencesStore(path)
    original = UserPreferences(
        theme="dark",
        history_enabled=True,
        network_access_enabled=True,
        network_access_token="abc-DEF-123_token",
        upstream_suggestions_enabled=True,
        update_check_enabled=False,
        last_update_check_ms=1_700_000_000_000,
        engine_enabled={"duckduckgo": True, "wikipedia": False},
    )
    store.save(original)
    reloaded = store.load()
    assert reloaded == original
    assert reloaded.network_access_token == "abc-DEF-123_token"


def test_network_access_token_defaults_empty_for_old_prefs(tmp_path: Path) -> None:
    """An older prefs.json without the token field loads with an empty token, not a crash."""
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"network_access_enabled": True}), encoding="utf-8")
    loaded = JsonPreferencesStore(path).load()
    assert loaded.network_access_enabled is True
    assert loaded.network_access_token == ""


def test_load_returns_defaults_when_file_missing(tmp_path: Path) -> None:
    store = JsonPreferencesStore(tmp_path / "absent.json")
    assert store.load() == UserPreferences()


def test_load_is_lenient_with_missing_fields(tmp_path: Path) -> None:
    """Older `prefs.json` schemas keep loading; missing fields fall back to defaults."""
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"theme": "light", "unknown_future_field": 42}), encoding="utf-8")
    loaded = JsonPreferencesStore(path).load()
    assert loaded.theme == "light"
    assert loaded.history_enabled is False
    assert loaded.update_check_enabled is True


def test_load_returns_defaults_on_garbage_json(tmp_path: Path) -> None:
    path = tmp_path / "prefs.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert JsonPreferencesStore(path).load() == UserPreferences()


def test_save_is_atomic_via_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If `os.replace` fails, the real `prefs.json` must not be observable mid-write."""
    path = tmp_path / "prefs.json"
    store = JsonPreferencesStore(path)
    store.save(UserPreferences(theme="dark"))

    def _exploding_replace(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("simulated interrupt")

    monkeypatch.setattr("searchmob_desktop.prefs.os.replace", _exploding_replace)
    with pytest.raises(OSError, match="simulated interrupt"):
        store.save(UserPreferences(theme="light"))

    # The tmp file may still exist, but the real file's content is the pre-failure one.
    assert JsonPreferencesStore(path).load().theme == "dark"


def test_with_update_check_stamped_returns_copy() -> None:
    original = UserPreferences()
    stamped = original.with_update_check_stamped(123)
    assert original.last_update_check_ms == 0
    assert stamped.last_update_check_ms == 123
    assert stamped.theme == original.theme
