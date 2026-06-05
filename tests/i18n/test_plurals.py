"""CLDR plural categories, the `trn` plural lookup, and `trc`/context disambiguation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from searchmob_desktop import i18n
from searchmob_desktop.i18n import catalog, plural_categories, plural_category, representative_count


@pytest.fixture(autouse=True)
def _reset_locale() -> None:
    catalog.set_active_locale("en")
    yield
    catalog.set_active_locale("en")


def test_plural_category_arabic_has_six_forms() -> None:
    cats = {n: plural_category("ar", n) for n in (0, 1, 2, 3, 11, 100)}
    assert cats == {0: "zero", 1: "one", 2: "two", 3: "few", 11: "many", 100: "other"}
    assert plural_categories("ar") == ("zero", "one", "two", "few", "many", "other")


def test_plural_category_english_and_chinese() -> None:
    assert plural_category("en", 1) == "one"
    assert plural_category("en", 0) == "other" and plural_category("en", 5) == "other"
    assert plural_categories("zh") == ("other",)  # Chinese makes no count distinction
    assert plural_category("fr", 0) == "one" and plural_category("fr", 2) == "other"


def test_representative_count_picks_smallest_in_category() -> None:
    assert representative_count("ar", "few") == 3
    assert representative_count("ar", "many") == 11
    assert representative_count("en", "one") == 1


def test_trn_english_fallback_uses_the_two_forms() -> None:
    assert i18n.trn(1, "{n} result", "{n} results") == "1 result"
    assert i18n.trn(0, "{n} result", "{n} results") == "0 results"
    assert i18n.trn(5, "{n} result", "{n} results") == "5 results"


def test_trn_uses_authored_cldr_forms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "_LOCALES_DIR", tmp_path)
    catalog._load_plural_catalog.cache_clear()
    # Minimal Arabic plural set keyed by the English "other" form.
    (tmp_path / "ar.plurals.json").write_text(
        json.dumps(
            {
                "{n} results": {
                    "zero": "zero-{n}",
                    "one": "one-{n}",
                    "two": "two-{n}",
                    "few": "few-{n}",
                    "many": "many-{n}",
                    "other": "other-{n}",
                }
            }
        ),
        encoding="utf-8",
    )
    catalog.set_active_locale("ar")
    assert i18n.trn(0, "{n} result", "{n} results") == "zero-0"
    assert i18n.trn(2, "{n} result", "{n} results") == "two-2"
    assert i18n.trn(3, "{n} result", "{n} results") == "few-3"
    assert i18n.trn(11, "{n} result", "{n} results") == "many-11"
    # A missing category would fall back to "other"; here all are present.
    assert i18n.trn(100, "{n} result", "{n} results") == "other-100"


def test_context_disambiguates_same_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "_LOCALES_DIR", tmp_path)
    catalog._load_catalog.cache_clear()
    sep = i18n.CONTEXT_SEP
    (tmp_path / "fr.json").write_text(
        json.dumps(
            {
                f"sort order{sep}Date": "Date (tri)",
                f"calendar{sep}Date": "Date (jour)",
                "Date": "Date (nu)",
            }
        ),
        encoding="utf-8",
    )
    catalog.set_active_locale("fr")
    assert i18n.trc("sort order", "Date") == "Date (tri)"
    assert i18n.trc("calendar", "Date") == "Date (jour)"
    assert i18n.tr("Date") == "Date (nu)"  # no context -> bare key
    # An unknown context falls back to the English source, not the bare translation.
    assert i18n.trc("nowhere", "Date") == "Date"
