"""Read-only word dictionary with phonetic and length indexes.

Mirrors the Android `Dictionary`: a frozen lookup structure built once from a `word -> weight` map.
On top of the raw weights it precomputes two indexes the corrector relies on for cheap candidate
generation:

* `by_phonetic` -- phonetic code -> words that encode to that code (similar-sounding candidates).
* `by_length` -- word length -> words of that length (lets the corrector scan only words whose
  length is within the allowed edit budget of the query term).

All lookups are pure and fail soft: missing keys yield empty results or zero weight rather than
raising.
"""

from __future__ import annotations

from collections.abc import Callable

from searchmob_desktop.engines.correct.phonetics import phonetic_codes as default_phonetic_codes


class Dictionary:
    """An indexed, read-only view over a `word -> weight` map.

    Construct via the `build` classmethod; the `__init__` constructor takes the prebuilt indexes
    directly and is treated as internal.
    """

    def __init__(
        self,
        weights: dict[str, int],
        by_phonetic: dict[str, list[str]],
        by_length: dict[int, list[str]],
    ) -> None:
        self._weights = weights
        self._by_phonetic = by_phonetic
        self._by_length = by_length

    @classmethod
    def build(
        cls,
        weights: dict[str, int],
        phonetic_codes: Callable[[str], list[str]] = default_phonetic_codes,
    ) -> Dictionary:
        """Build a `Dictionary`, indexing each word by its phonetic codes and by its length."""
        by_phonetic: dict[str, list[str]] = {}
        by_length: dict[int, list[str]] = {}
        for word in weights:
            for code in phonetic_codes(word):
                by_phonetic.setdefault(code, []).append(word)
            by_length.setdefault(len(word), []).append(word)
        return cls(weights, by_phonetic, by_length)

    @property
    def size(self) -> int:
        """Number of words in the dictionary."""
        return len(self._weights)

    def contains(self, term: str) -> bool:
        """Whether `term` is a known word."""
        return term in self._weights

    def weight(self, term: str) -> int:
        """Frequency weight of `term`, or 0 if it is not in the dictionary."""
        return self._weights.get(term, 0)

    def phonetic(self, code: str) -> list[str]:
        """Words that encode to phonetic `code`, or an empty list if none do."""
        return self._by_phonetic.get(code, [])

    def near_length(self, length: int, delta: int) -> list[str]:
        """Words whose length is within `delta` of `length` (inclusive on both sides)."""
        result: list[str] = []
        for candidate_length in range(length - delta, length + delta + 1):
            result.extend(self._by_length.get(candidate_length, []))
        return result
