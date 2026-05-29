"""End-to-end behavior of `OnDeviceSpellCorrector` and the no-op variant."""

from __future__ import annotations

from searchmob_desktop.engines.correct.corrector import (
    Correction,
    NoopSpellCorrector,
    OnDeviceSpellCorrector,
)
from searchmob_desktop.engines.correct.dictionary import Dictionary


def _dictionary() -> Dictionary:
    return Dictionary.build(
        {
            "phone": 500000,
            "photograph": 220000,
            "definitely": 200000,
            "receive": 300000,
            "separate": 150000,
            "cat": 90000,
            "python": 80000,
            "search": 400000,
            "hello": 250000,
            "world": 240000,
        }
    )


def _corrector() -> OnDeviceSpellCorrector:
    return OnDeviceSpellCorrector(dictionary=_dictionary)


def test_edit_distance_typo_is_corrected() -> None:
    result = _corrector().suggest("definately")
    assert result is not None
    assert result.corrected == "definitely"
    assert 0.0 < result.confidence <= 1.0


def test_phonetic_near_miss_is_corrected() -> None:
    # "fotograph" differs from "photograph" in its first letter, so the edit-distance path
    # (which requires a shared first character) cannot reach it. Only the phonetic bucket can,
    # and Jaro-Winkler similarity (~0.90) clears the threshold.
    result = _corrector().suggest("fotograph")
    assert result is not None
    assert result.corrected == "photograph"


def test_correct_word_returns_none() -> None:
    assert _corrector().suggest("phone") is None


def test_multiword_corrects_only_wrong_token() -> None:
    result = _corrector().suggest("hello wrold")
    assert result is not None
    assert result.corrected == "hello world"


def test_multiword_all_correct_returns_none() -> None:
    assert _corrector().suggest("hello world") is None


def test_none_dictionary_returns_none() -> None:
    corrector = OnDeviceSpellCorrector(dictionary=lambda: None)
    assert corrector.suggest("definately") is None


def test_empty_and_blank_return_none() -> None:
    corrector = _corrector()
    assert corrector.suggest("") is None
    assert corrector.suggest("   ") is None


def test_respects_min_term_length() -> None:
    # "ct" is below the default min length of 3, so it is left untouched.
    corrector = OnDeviceSpellCorrector(dictionary=_dictionary, min_term_length=3)
    assert corrector.suggest("ct") is None


def test_threshold_blocks_distant_candidates() -> None:
    # A very high threshold rejects everything, so no correction is produced.
    corrector = OnDeviceSpellCorrector(dictionary=_dictionary, similarity_threshold=0.999)
    assert corrector.suggest("definately") is None


def test_non_ascii_token_is_left_alone() -> None:
    # Digits / mixed scripts are skipped entirely.
    corrector = _corrector()
    assert corrector.suggest("abc123") is None
    assert corrector.suggest("你好世界") is None


def test_never_raises_on_garbage() -> None:
    corrector = _corrector()
    for nasty in ["", "   ", "!!!", "123 456", "éèê", "a" * 1000, "\n\t"]:
        # Must not raise; result may be None or a Correction.
        result = corrector.suggest(nasty)
        assert result is None or isinstance(result, Correction)


def test_noop_corrector_returns_none() -> None:
    assert NoopSpellCorrector().suggest("definately") is None
