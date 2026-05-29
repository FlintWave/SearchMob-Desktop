"""Loading and history augmentation for `AssetDictionaryLoader`."""

from __future__ import annotations

import pytest

from searchmob_desktop.engines.correct.loader import AssetDictionaryLoader


def test_current_is_none_before_load() -> None:
    loader = AssetDictionaryLoader()
    assert loader.current() is None


def test_load_real_asset_has_words() -> None:
    loader = AssetDictionaryLoader()
    dictionary = loader.load()
    assert dictionary.size > 0
    # A few common words should be present in the bundled list.
    assert dictionary.contains("the")
    assert loader.current() is dictionary


def test_load_is_idempotent() -> None:
    loader = AssetDictionaryLoader()
    first = loader.load()
    second = loader.load()
    assert first is second


def test_history_augmentation_adds_term_with_weight() -> None:
    term = "zzqxnovelword"
    loader = AssetDictionaryLoader(history_terms=lambda: [term], history_weight=15000)
    dictionary = loader.load()
    assert dictionary.contains(term)
    assert dictionary.weight(term) == 15000


def test_history_multiword_splits_into_subterms() -> None:
    loader = AssetDictionaryLoader(history_terms=lambda: ["zzqfoo zzqbar"], history_weight=12345)
    dictionary = loader.load()
    assert dictionary.weight("zzqfoo") == 12345
    assert dictionary.weight("zzqbar") == 12345


def test_history_does_not_override_existing_word() -> None:
    loader = AssetDictionaryLoader(history_terms=lambda: ["the"], history_weight=15000)
    dictionary = loader.load()
    # "the" already has a (much larger) real weight; history must not clobber it.
    assert dictionary.weight("the") != 15000


def test_raising_history_callable_does_not_break_load() -> None:
    def boom() -> list[str]:
        raise RuntimeError("history unavailable")

    loader = AssetDictionaryLoader(history_terms=boom)
    dictionary = loader.load()
    assert dictionary.size > 0


def test_load_from_explicit_asset_path(tmp_path: pytest.TempPathFactory) -> None:
    import gzip
    from pathlib import Path

    path = Path(str(tmp_path)) / "words.txt.gz"
    payload = b"alpha\t100\nbeta\t50\nbad\nzero\t0\n"
    path.write_bytes(gzip.compress(payload))

    loader = AssetDictionaryLoader(asset_path=str(path))
    dictionary = loader.load()
    assert dictionary.contains("alpha")
    assert dictionary.weight("beta") == 50
    assert not dictionary.contains("bad")  # no weight column
    assert not dictionary.contains("zero")  # zero weight skipped
