"""Behavior of the phonetic encoder used to bucket similar-sounding words."""

from __future__ import annotations

from searchmob_desktop.engines.correct.phonetics import phonetic_codes


def test_normal_word_has_codes() -> None:
    codes = phonetic_codes("phone")
    assert codes
    assert all(code for code in codes)


def test_similar_sounding_words_share_a_code() -> None:
    a = set(phonetic_codes("katherine"))
    b = set(phonetic_codes("catherine"))
    assert a & b


def test_misspelling_shares_a_code() -> None:
    a = set(phonetic_codes("definately"))
    b = set(phonetic_codes("definitely"))
    assert a & b


def test_no_duplicate_when_primary_equals_alternate() -> None:
    codes = phonetic_codes("catherine")
    assert len(codes) == len(set(codes))


def test_empty_input_yields_no_codes() -> None:
    assert phonetic_codes("") == []
