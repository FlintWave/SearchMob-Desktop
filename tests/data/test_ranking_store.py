"""Ranking-rules persistence: vault round-trip and fail-soft when no vault is available."""

from __future__ import annotations

import pytest

from searchmob_desktop.data import ranking_store
from searchmob_desktop.engines.rank import DEFAULT_SAMPLE_LENSES, Lens, RankingRules, RankRule


class _FakePrefs:
    """In-memory stand-in for EncryptedPreferences (get/put over a dict)."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def put(self, key: str, value: str) -> None:
        self._data[key] = value


def test_save_then_load_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakePrefs()
    monkeypatch.setattr(ranking_store, "open_encrypted_prefs", lambda: fake)

    rules = RankingRules().with_domain_rule("spam.example", RankRule.BLOCK)
    assert ranking_store.save_ranking_rules(rules) is True
    # The blob is stored under the documented key.
    assert ranking_store.RANKING_KEY in fake._data

    loaded = ranking_store.load_ranking_rules()
    assert loaded.domain_rules.get("spam.example") == RankRule.BLOCK


def test_load_seeds_sample_scopes_without_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    # With no vault and no saved profile, the sample scopes are the default lens set so the scope
    # selector is useful before any search.
    monkeypatch.setattr(ranking_store, "open_encrypted_prefs", lambda: None)
    loaded = ranking_store.load_ranking_rules()
    assert loaded.lenses == DEFAULT_SAMPLE_LENSES
    assert loaded.domain_rules == {}


def test_save_reports_failure_without_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ranking_store, "open_encrypted_prefs", lambda: None)
    assert ranking_store.save_ranking_rules(RankingRules()) is False


def test_load_empty_blob_seeds_sample_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ranking_store, "open_encrypted_prefs", lambda: _FakePrefs())
    assert ranking_store.load_ranking_rules().lenses == DEFAULT_SAMPLE_LENSES


def test_load_keeps_user_lenses_without_seeding(monkeypatch: pytest.MonkeyPatch) -> None:
    # A profile that already has a lens is returned as-is; samples are not re-injected, so the user
    # can keep just their own scopes.
    fake = _FakePrefs()
    monkeypatch.setattr(ranking_store, "open_encrypted_prefs", lambda: fake)
    ranking_store.save_ranking_rules(RankingRules(lenses=(Lens(name="Mine"),)))
    loaded = ranking_store.load_ranking_rules()
    assert [lens.name for lens in loaded.lenses] == ["Mine"]
