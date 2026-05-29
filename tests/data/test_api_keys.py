"""BYO API-key resolution: vault precedence, env fallback, unknown engines, fail-soft vault read."""

from __future__ import annotations

import pytest

from searchmob_desktop.data import api_keys
from searchmob_desktop.data.api_keys import (
    BRAVE_KEY,
    BRAVE_KEY_ENV,
    KAGI_KEY,
    KAGI_KEY_ENV,
    read_vault_api_keys,
    resolve_api_key,
)


def test_vault_value_takes_precedence_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BRAVE_KEY_ENV, "from-env")
    assert resolve_api_key("brave", {BRAVE_KEY: "from-vault"}) == "from-vault"


def test_env_used_when_vault_lacks_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KAGI_KEY_ENV, "env-kagi")
    assert resolve_api_key("kagi-api", {}) == "env-kagi"


def test_none_when_neither_source_has_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KAGI_KEY_ENV, raising=False)
    assert resolve_api_key("kagi-api", {}) is None


def test_unknown_engine_returns_none() -> None:
    assert resolve_api_key("not-an-engine", {KAGI_KEY: "x"}) is None


def test_empty_string_key_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KAGI_KEY_ENV, "env-kagi")
    # An empty vault value should not win over a real env value.
    assert resolve_api_key("kagi-api", {KAGI_KEY: ""}) == "env-kagi"


def test_read_vault_api_keys_is_fail_soft_without_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    # Point the metadata store at an empty temp dir so there is no vault: should yield {}.
    class _FakeMetaStore:
        def __init__(self) -> None:
            from pathlib import Path

            assert isinstance(tmp_path, object)
            self.path = Path(str(tmp_path)) / "vault.json"

    monkeypatch.setattr(api_keys, "BootstrapMetadataStore", _FakeMetaStore)
    assert read_vault_api_keys() == {}
