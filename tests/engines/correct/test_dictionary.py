"""Index and lookup behavior of `Dictionary`."""

from __future__ import annotations

from searchmob_desktop.engines.correct.dictionary import Dictionary


def _dictionary() -> Dictionary:
    return Dictionary.build(
        {
            "phone": 100,
            "fone": 5,
            "cat": 50,
            "cats": 40,
            "dog": 30,
        }
    )


def test_size() -> None:
    assert _dictionary().size == 5


def test_contains_and_weight() -> None:
    d = _dictionary()
    assert d.contains("phone")
    assert not d.contains("missing")
    assert d.weight("phone") == 100
    assert d.weight("missing") == 0


def test_phonetic_buckets_similar_sounds() -> None:
    d = _dictionary()
    from searchmob_desktop.engines.correct.phonetics import phonetic_codes

    code = phonetic_codes("phone")[0]
    bucket = set(d.phonetic(code))
    assert "phone" in bucket
    assert "fone" in bucket


def test_phonetic_missing_code_is_empty() -> None:
    assert _dictionary().phonetic("ZZZZ") == []


def test_near_length() -> None:
    d = _dictionary()
    # length 3 +/- 0 -> only 3-letter words
    assert set(d.near_length(3, 0)) == {"cat", "dog"}
    # length 4 +/- 1 -> 3, 4, 5 letter words
    near = set(d.near_length(4, 1))
    assert near == {"cat", "dog", "cats", "phone", "fone"}


def test_near_length_out_of_range_is_empty() -> None:
    assert _dictionary().near_length(99, 1) == []
