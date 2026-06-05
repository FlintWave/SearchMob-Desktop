"""The i18n locale registry and runtime catalog: resolution, fallback, formatting, and switching."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from searchmob_desktop import i18n
from searchmob_desktop.i18n import catalog


@pytest.fixture(autouse=True)
def _reset_locale() -> None:
    catalog.set_active_locale("en")
    yield
    catalog.set_active_locale("en")


def test_supported_locales_are_the_top_ten() -> None:
    tags = [loc.tag for loc in i18n.SUPPORTED_LOCALES]
    assert tags == ["en", "zh", "hi", "es", "ar", "fr", "bn", "pt", "id", "ur"]
    assert {loc.tag for loc in i18n.SUPPORTED_LOCALES if loc.rtl} == {"ar", "ur"}


def test_normalize_tag_reduces_region_subtags() -> None:
    assert i18n.normalize_tag("es-MX") == "es"
    assert i18n.normalize_tag("pt_BR") == "pt"
    assert i18n.normalize_tag("zh-Hans-CN") == "zh"
    assert i18n.normalize_tag("xx-YY") == "en"  # unsupported -> default
    assert i18n.normalize_tag(None) == "en"


def test_is_rtl() -> None:
    assert i18n.is_rtl("ar") and i18n.is_rtl("ur-PK")
    assert not i18n.is_rtl("en") and not i18n.is_rtl("es")


def test_english_returns_source_unchanged() -> None:
    assert i18n.tr("Search the web") == "Search the web"


def test_translation_and_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Point the catalog at a temp locales dir with a tiny Spanish file, bypassing the lru cache.
    monkeypatch.setattr(catalog, "_LOCALES_DIR", tmp_path)
    catalog._load_catalog.cache_clear()
    (tmp_path / "es.json").write_text(
        json.dumps({"Search the web": "Buscar en la web"}), encoding="utf-8"
    )
    catalog.set_active_locale("es")
    assert i18n.tr("Search the web") == "Buscar en la web"
    # A string with no translation falls back to the English source.
    assert i18n.tr("Settings") == "Settings"


def test_named_format_args_survive_translation() -> None:
    assert i18n.tr("{count} results", count=12) == "12 results"
    # A bad placeholder degrades to the unformatted string rather than raising.
    assert i18n.tr("{count} results") == "{count} results"


def test_switching_notifies_subscribers() -> None:
    seen: list[str] = []
    unsubscribe = catalog.subscribe(seen.append)
    catalog.set_active_locale("fr")
    catalog.set_active_locale("ar")
    assert seen == ["fr", "ar"]
    unsubscribe()
    catalog.set_active_locale("es")
    assert seen == ["fr", "ar"]  # no longer notified after unsubscribe
